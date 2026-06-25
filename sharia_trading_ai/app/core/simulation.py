"""
SIMULASI EKSEKUSI HARIAN (paper trading) — bahan pembelajaran akurasi prediksi.

Setiap kartu BUY dari Pusat Keputusan direkam otomatis sebagai transaksi
simulasi (tanpa uang riil), lalu ditutup otomatis saat:
  - harga menyentuh TARGET (profit),
  - harga menyentuh STOP LOSS (rugi), atau
  - melewati HORIZON hari bursa (tutup di harga terakhir).

Akumulasi hasil (ROI %, win-rate, equity curve) menjadi:
  1. Sarana belajar pengguna: seberapa akurat rekomendasi aplikasi.
  2. Umpan balik algoritma: roi.adaptive_strategy() memakai data simulasi
     sebagai dasar ambang akurasi BELI saat data realized masih sedikit.
  3. Konteks prompt Claude (ai_advisor) agar analisanya sadar track-record.

Murni paper-trade: TIDAK menyentuh portfolio.json / trades.json.
ROI dihitung BERSIH (fee beli+jual default broker) agar apple-to-apple
dengan jurnal transaksi nyata.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from app.config import BASE_DIR, MM
from app.core import accounts, bei_calendar
from app.data import provider

STORE = BASE_DIR.parent / "data_store" / "simulations.json"
STORE.parent.mkdir(parents=True, exist_ok=True)

HORIZON_DAYS = 20            # hari bursa maksimal posisi simulasi terbuka (~1 bulan)
FALLBACK_TARGET_PCT = 7.0    # selaras BASE_TARGET_PCT decisions / Jalur 7%
FALLBACK_STOP_PCT = -7.0     # selaras CUT_LOSS_PCT


# --------------------------- persistence --------------------------- #
def _load() -> dict[str, Any]:
    if not STORE.exists():
        return {"meta": {}, "trades": []}
    try:
        d = json.loads(STORE.read_text())
        if isinstance(d, dict) and "trades" in d:
            return d
    except Exception:  # noqa: BLE001
        pass
    return {"meta": {}, "trades": []}


def _save(d: dict[str, Any]) -> None:
    STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2))


def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and not bei_calendar.is_holiday(d)


def _net_roi_pct(entry: float, exit_price: float) -> float:
    """ROI bersih %: modal termasuk fee beli, hasil dipotong fee jual (default broker)."""
    fee_buy, fee_sell = accounts.fees_for(None)
    cost = entry * (1 + fee_buy / 100)
    proceeds = exit_price * (1 - fee_sell / 100)
    return round((proceeds - cost) / cost * 100, 2) if cost else 0.0


def _live_price(ticker: str) -> Optional[float]:
    """Harga selive mungkin (intraday 5m, fallback close harian) — pola portfolio."""
    from app.config import settings
    ttl = settings.price_ttl_seconds
    try:
        intr = provider.get_history(ticker, period="1d", interval="5m", ttl=ttl)
        if intr is not None and not intr.empty:
            return round(float(intr["Close"].iloc[-1]), 2)
    except Exception:  # noqa: BLE001
        pass
    try:
        df = provider.get_history(ticker, period="5d", ttl=ttl)
        if df is not None and not df.empty:
            return round(float(df["Close"].iloc[-1]), 2)
    except Exception:  # noqa: BLE001
        pass
    return None


def list_all() -> list[dict[str, Any]]:
    return _load()["trades"]


def delete(sim_id: int) -> bool:
    d = _load()
    new = [t for t in d["trades"] if t.get("id") != sim_id]
    if len(new) == len(d["trades"]):
        return False
    d["trades"] = new
    _save(d)
    return True


# --------------------------- capture harian --------------------------- #
def capture_today(force: bool = False) -> dict[str, Any]:
    """Rekam SETIAP kartu BUY Pusat Keputusan hari ini sebagai simulasi OPEN.

    Dedup: 1x per hari (meta.last_capture) & per ticker yang masih OPEN.
    Entry = harga rencana undervalue (plan.entry) atau harga live.
    Target / Stop dari rencana undervalue; fallback +7% / −7% (Jalur 7%).
    """
    today = date.today()
    if not force and not _is_trading_day(today):
        return {"ok": False, "skipped": "bukan hari bursa", "added": 0}

    d = _load()
    if not force and d["meta"].get("last_capture") == today.isoformat():
        return {"ok": False, "skipped": "sudah direkam hari ini", "added": 0,
                "last_capture": d["meta"].get("last_capture")}

    # lazy import — hindari siklus impor (decisions → roi → simulation)
    from app.core import decisions, undervalue

    dec = decisions.build_decisions()
    open_tickers = {t["ticker"] for t in d["trades"] if t.get("status") == "OPEN"}
    added: list[dict[str, Any]] = []
    next_id = max((t.get("id", 0) for t in d["trades"]), default=0) + 1

    for rec in dec.get("buy", []):
        tk = (rec.get("ticker") or "").upper()
        if not tk or tk in open_tickers:
            continue
        # rencana trading dari Screener Undervalue (entry/stop/target empiris)
        plan = None
        try:
            uv = undervalue.evaluate(tk)
            plan = (uv or {}).get("plan")
        except Exception:  # noqa: BLE001
            plan = None
        entry = (plan or {}).get("entry") or _live_price(tk)
        if not entry or entry <= 0:
            continue
        target = (plan or {}).get("target") or round(entry * (1 + FALLBACK_TARGET_PCT / 100), 2)
        stop = (plan or {}).get("stop_loss") or round(entry * (1 + FALLBACK_STOP_PCT / 100), 2)
        sim = {
            "id": next_id,
            "ticker": tk,
            "status": "OPEN",
            "opened": today.isoformat(),
            "entry": round(float(entry), 2),
            "target": round(float(target), 2),
            "stop_loss": round(float(stop), 2),
            "horizon_days": HORIZON_DAYS,
            # metadata learning (kondisi saat sinyal dibuat)
            "conviction": rec.get("conviction"),
            "akurasi_pct": rec.get("akurasi_pct"),
            "uv_score": rec.get("uv_score"),
            "funnel_skor": rec.get("funnel_skor"),
            "confidence": rec.get("confidence"),
            "context": rec.get("context"),
            "reason": (rec.get("reason") or "")[:160],
        }
        d["trades"].append(sim)
        added.append(sim)
        open_tickers.add(tk)
        next_id += 1

    d["meta"]["last_capture"] = today.isoformat()
    _save(d)
    return {"ok": True, "added": len(added), "trades": added,
            "buy_signals": len(dec.get("buy", [])), "date": today.isoformat()}


# --------------------------- evaluasi posisi terbuka --------------------------- #
def evaluate_open() -> dict[str, Any]:
    """Periksa tiap simulasi OPEN terhadap data OHLC harian sesudah tanggal entry.

    Urutan per bar (konservatif): Stop Loss dicek lebih dulu, lalu Target.
    Lewat horizon hari bursa → tutup di close bar terakhir (HORIZON).
    """
    d = _load()
    closed: list[dict[str, Any]] = []
    for t in d["trades"]:
        if t.get("status") != "OPEN":
            continue
        try:
            df = provider.get_history(t["ticker"], period="6mo")
        except Exception:  # noqa: BLE001
            continue
        if df is None or df.empty:
            continue
        try:
            opened = datetime.fromisoformat(t["opened"]).date()
        except Exception:  # noqa: BLE001
            continue
        bars = df[[c for c in ("High", "Low", "Close") if c in df.columns]].dropna()
        bars = bars[[i.date() > opened for i in bars.index]]   # hanya bar SETELAH entry
        days = 0
        for idx, row in bars.iterrows():
            days += 1
            hi, lo, cl = float(row["High"]), float(row["Low"]), float(row["Close"])
            exit_price = reason = None
            if lo <= t["stop_loss"]:
                exit_price, reason = t["stop_loss"], "STOP_LOSS"
            elif hi >= t["target"]:
                exit_price, reason = t["target"], "TARGET"
            elif days >= int(t.get("horizon_days") or HORIZON_DAYS):
                exit_price, reason = cl, "HORIZON"
            if exit_price is not None:
                roi_pct = _net_roi_pct(t["entry"], exit_price)
                t.update({
                    "status": "CLOSED",
                    "closed": idx.date().isoformat(),
                    "exit_price": round(exit_price, 2),
                    "exit_reason": reason,
                    "roi_pct": roi_pct,
                    "win": roi_pct > 0,
                    "days_held": days,
                })
                closed.append(t)
                break
    d["meta"]["last_evaluate"] = datetime.now().isoformat(timespec="seconds")
    _save(d)
    return {"ok": True, "closed": len(closed), "trades": closed}


# --------------------------- statistik & equity curve --------------------------- #
def _band(conv: Optional[float]) -> str:
    if conv is None:
        return "tanpa skor"
    if conv >= 70:
        return "conviction ≥70"
    if conv >= 55:
        return "conviction 55–70"
    return "conviction <55"


def stats(with_live: bool = True) -> dict[str, Any]:
    d = _load()
    trades = d["trades"]
    open_t = [t for t in trades if t.get("status") == "OPEN"]
    closed_t = sorted([t for t in trades if t.get("status") == "CLOSED"],
                      key=lambda t: (t.get("closed") or "", t.get("id", 0)))

    # posisi terbuka: P/L berjalan (harga live) + sisa horizon
    open_rows = []
    for t in open_t:
        cur = _live_price(t["ticker"]) if with_live else None
        run = _net_roi_pct(t["entry"], cur) if cur else None
        elapsed = 0
        try:
            od = datetime.fromisoformat(t["opened"]).date()
            cd = od
            while cd < date.today():
                cd = date.fromordinal(cd.toordinal() + 1)
                if _is_trading_day(cd):
                    elapsed += 1
        except Exception:  # noqa: BLE001
            pass
        open_rows.append({**t, "current_price": cur, "running_roi_pct": run,
                          "days_elapsed": elapsed,
                          "days_left": max(0, int(t.get("horizon_days") or HORIZON_DAYS) - elapsed)})

    # agregat closed
    n = len(closed_t)
    wins = sum(1 for t in closed_t if t.get("win"))
    rois = [t["roi_pct"] for t in closed_t if t.get("roi_pct") is not None]
    agg = {
        "n_open": len(open_t), "n_closed": n, "n_total": len(trades),
        "win_rate": round(wins / n * 100, 1) if n else None,
        "avg_roi": round(sum(rois) / n, 2) if n else None,
        "cum_roi_pct": round(sum(rois), 2) if n else None,   # akumulasi ROI per-trade (modal sama tiap trade)
        "best": round(max(rois), 2) if rois else None,
        "worst": round(min(rois), 2) if rois else None,
        "by_exit": {k: sum(1 for t in closed_t if t.get("exit_reason") == k)
                    for k in ("TARGET", "STOP_LOSS", "HORIZON")},
    }

    # equity curve: ROI kumulatif rata (bobot sama per trade)
    curve, cum = [], 0.0
    for i, t in enumerate(closed_t, 1):
        cum += t.get("roi_pct") or 0
        curve.append({"n": i, "date": t.get("closed"), "ticker": t["ticker"],
                      "roi_pct": t.get("roi_pct"), "cum_roi_pct": round(cum / i, 2),
                      "cum_pl": round(cum, 2)})

    # breakdown learning: per band conviction & per confidence
    def _group(key_fn) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for t in closed_t:
            k = key_fn(t)
            g = out.setdefault(k, {"n": 0, "wins": 0, "roi_sum": 0.0})
            g["n"] += 1
            g["wins"] += 1 if t.get("win") else 0
            g["roi_sum"] += t.get("roi_pct") or 0
        return {k: {"n": v["n"], "win_rate": round(v["wins"] / v["n"] * 100, 1),
                    "avg_roi": round(v["roi_sum"] / v["n"], 2)} for k, v in out.items()}

    by_conviction = _group(lambda t: _band(t.get("conviction")))
    by_confidence = _group(lambda t: t.get("confidence") or "n/a")

    return {
        "meta": d["meta"],
        "summary": agg,
        "open": open_rows,
        "closed": closed_t,
        "curve": curve,
        "by_conviction": by_conviction,
        "by_confidence": by_confidence,
        "target_pct": MM.PROFIT_FUND_PCT,
    }


# --------------------------- learning (umpan balik algoritma) --------------------------- #
def learning() -> dict[str, Any]:
    """Sintesis insight dari hasil simulasi → bahan kalibrasi algoritma berikutnya."""
    s = stats(with_live=False)
    agg = s["summary"]
    notes: list[str] = []
    n = agg["n_closed"]

    if n == 0:
        notes.append("Belum ada simulasi tertutup — biarkan berjalan beberapa hari bursa; "
                     "sistem mulai belajar setelah posisi pertama ditutup (TP/SL/horizon).")
        return {"n_closed": 0, "win_rate": None, "avg_roi": None,
                "suggested_min_conviction": None, "notes": notes, "by_conviction": {}}

    wr, avg = agg["win_rate"], agg["avg_roi"]
    notes.append(f"Dari {n} simulasi tertutup: win-rate {wr}% · ROI rata-rata {avg}% per sinyal.")

    # band conviction mana yang terbukti profitabel?
    best_band, suggested = None, None
    for band, g in sorted(s["by_conviction"].items(), key=lambda kv: -(kv[1]["avg_roi"])):
        if g["n"] >= 3 and g["avg_roi"] > 0 and best_band is None:
            best_band = (band, g)
    if best_band:
        band, g = best_band
        notes.append(f"Band paling profitabel: {band} (n={g['n']}, win {g['win_rate']}%, "
                     f"avg {g['avg_roi']}%) → prioritaskan sinyal di band ini.")
        if "≥70" in band:
            suggested = 70.0
        elif "55" in band:
            suggested = 55.0
    if wr is not None and wr < 50:
        notes.append(f"Win-rate simulasi {wr}% < 50% → ambang akurasi BELI dinaikkan otomatis "
                     "(strategi adaptif) agar sinyal lebih selektif.")
    exits = agg["by_exit"]
    if exits.get("STOP_LOSS", 0) > exits.get("TARGET", 0):
        notes.append("Stop loss lebih sering tersentuh daripada target → pertimbangkan entry lebih "
                     "sabar (tunggu pullback) atau target lebih realistis.")
    return {"n_closed": n, "win_rate": wr, "avg_roi": avg,
            "suggested_min_conviction": suggested, "notes": notes,
            "by_conviction": s["by_conviction"]}


def summary_for_ai() -> Optional[dict[str, Any]]:
    """Ringkasan kompak track-record simulasi → disisipkan ke prompt Claude."""
    try:
        s = stats(with_live=False)
    except Exception:  # noqa: BLE001
        return None
    agg = s["summary"]
    if not agg["n_closed"]:
        return None
    return {
        "n_simulasi_tertutup": agg["n_closed"],
        "win_rate_pct": agg["win_rate"],
        "avg_roi_pct_per_sinyal": agg["avg_roi"],
        "exit": agg["by_exit"],
        "per_band_conviction": s["by_conviction"],
        "catatan": ("Track-record SIMULASI otomatis atas rekomendasi BUY aplikasi ini "
                    "(paper trade, ROI bersih incl. fee). Gunakan utk mengkalibrasi "
                    "seberapa percaya diri saran Anda."),
    }
