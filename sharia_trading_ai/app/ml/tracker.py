"""
Track record sinyal ML: catat prediksi harian, evaluasi vs realisasi harga.

Lingkaran belajar (evaluasi prediksi vs realitas):
  1. log_today()        — tiap sore hari bursa (setelah tutup), simpan prediksi
                          ML + sinyal rule-based per ticker dari ranking funnel.
  2. evaluate_matured() — begitu horizon N hari bursa terlewati, hitung return
                          aktual dari harga penutupan dan nilai benar/salah.
  3. stats()            — track record agregat: hit rate, win rate, avg return,
                          kalibrasi P(BUY), perbandingan ML vs rule-based.
  4. calibrate()        — sarankan ambang confidence dari realisasi; disimpan ke
                          ml_track_summary.json dan dipakai ml_signal.predict()
                          (bila ML_CONF_THRESHOLD tidak di-set manual).

Penyimpanan: ml_data/ml_track.parquet (append harian, atomic replace).

CLI:
    python -m app.ml.tracker --log         # catat prediksi hari ini
    python -m app.ml.tracker --evaluate    # evaluasi baris yang sudah jatuh tempo
    python -m app.ml.tracker --report      # cetak track record
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

from app.ml.data_fetch import ML_DATA_DIR

STORE = ML_DATA_DIR / "ml_track.parquet"
SUMMARY = ML_DATA_DIR / "ml_track_summary.json"

# Sinyal rule-based yang dianggap "ajakan beli" (untuk perbandingan apel-ke-apel)
RULE_BUYISH = {"STRONG BUY", "BUY", "SPECULATIVE BUY", "ACCUMULATE"}

MIN_SAMPLES_CALIBRATION = 30   # jangan kalibrasi ambang dari sampel terlalu kecil


def _load() -> pd.DataFrame:
    if STORE.exists():
        return pd.read_parquet(STORE)
    return pd.DataFrame()


def _save(df: pd.DataFrame) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp.parquet")
    df.to_parquet(tmp)
    os.replace(tmp, STORE)


def _is_market_data_final(today: date) -> bool:
    """Bar harian IHSG untuk `today` sudah ada -> data penutupan final."""
    from app.data import provider
    try:
        idx = provider.get_index_history(period="1mo")
        if idx is None or idx.empty:
            return False
        last = pd.to_datetime(idx.index[-1])
        if last.tzinfo is not None:
            last = last.tz_localize(None)
        return last.date() >= today
    except Exception:
        return False


def log_today(ranking: Optional[list[dict]] = None, force: bool = False) -> dict[str, Any]:
    """Catat prediksi ML + sinyal rule hari ini (idempoten per tanggal)."""
    today = date.today()
    df = _load()
    if not df.empty and (df["date"] == today.isoformat()).any() and not force:
        return {"ok": True, "skipped": "sudah tercatat", "date": today.isoformat()}
    if not force and not _is_market_data_final(today):
        return {"ok": False, "skipped": "bar penutupan hari ini belum final/bukan hari bursa"}

    if ranking is None:
        from app.core import decisions
        ranking = decisions.build_ranking()

    from app.data import provider
    rows = []
    for s in ranking:
        tk = s.get("ticker") or ""
        ml = s.get("ml_signal") or {}
        if provider.is_us_ticker(tk) or not ml.get("available"):
            continue
        rows.append({
            "date": today.isoformat(),
            "ticker": tk,
            "price": float(s.get("current_price") or 0),
            "horizon": int(ml.get("horizon") or 5),
            "signal": ml.get("signal"),
            "p_buy": float(ml.get("p_buy") or 0),
            "p_hold": float(ml.get("p_hold") or 0),
            "p_sell": float(ml.get("p_sell") or 0),
            "confident": bool(ml.get("confident")),
            "rule_signal": s.get("final_signal"),
            "rule_skor": float(s.get("skor") or 0),
            "rule_keputusan": s.get("keputusan"),
            "evaluated": False,
            "eval_date": None,
            "realized_ret": None,
            "outcome": None,
            "ml_correct": None,
            "logged_at": datetime.now().isoformat(timespec="seconds"),
        })
    if not rows:
        return {"ok": False, "skipped": "tidak ada prediksi ML tersedia di ranking"}
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    _save(df)
    return {"ok": True, "logged": len(rows), "date": today.isoformat()}


def _outcome(ret: float, thr: float) -> int:
    return 1 if ret > thr else (-1 if ret < -thr else 0)


def evaluate_matured() -> dict[str, Any]:
    """Nilai baris yang horizonnya sudah lewat terhadap harga penutupan aktual."""
    from app.data import provider
    from app.ml.features import LABEL_THRESHOLDS

    df = _load()
    if df.empty:
        return {"ok": True, "evaluated": 0}
    pending = df[~df["evaluated"].astype(bool)]
    if pending.empty:
        return {"ok": True, "evaluated": 0}

    n_eval = 0
    hist_cache: dict[str, pd.DataFrame] = {}
    for i, row in pending.iterrows():
        tk = row["ticker"]
        h = int(row["horizon"])
        if tk not in hist_cache:
            try:
                hist = provider.get_history(tk, period="6mo", ttl=14400)
            except Exception:
                hist = pd.DataFrame()
            if not hist.empty:
                hist = hist.copy()
                idxs = pd.to_datetime(hist.index)
                try:
                    idxs = idxs.tz_localize(None)
                except TypeError:
                    pass
                hist.index = idxs.normalize()
            hist_cache[tk] = hist
        hist = hist_cache[tk]
        if hist.empty:
            continue
        t0 = pd.Timestamp(row["date"])
        pos = hist.index.get_indexer([t0])
        if pos[0] == -1:
            # tanggal log tidak ada di bar (data revisi/suspensi) -> cari bar berikut
            after = hist.index[hist.index >= t0]
            if len(after) == 0:
                continue
            pos = hist.index.get_indexer([after[0]])
        j = pos[0] + h
        if j >= len(hist):
            continue  # belum jatuh tempo
        base = float(hist["Close"].iloc[pos[0]])
        fut = float(hist["Close"].iloc[j])
        if base <= 0:
            continue
        ret = fut / base - 1
        thr = LABEL_THRESHOLDS.get(h, 0.02)
        out = _outcome(ret, thr)
        sig = row["signal"]
        correct = (sig == "BUY" and out == 1) or (sig == "SELL" and out == -1) \
            or (sig == "HOLD" and out == 0)
        df.loc[i, ["evaluated", "eval_date", "realized_ret", "outcome", "ml_correct"]] = \
            [True, str(hist.index[j].date()), round(ret, 5), out, bool(correct)]
        n_eval += 1

    if n_eval:
        _save(df)
        _write_summary(df)
    return {"ok": True, "evaluated": n_eval}


def _grp_stats(g: pd.DataFrame) -> dict[str, Any]:
    if g.empty:
        return {"n": 0}
    return {
        "n": int(len(g)),
        "hit_rate": round(float(g["ml_correct"].mean()), 3),
        "win_rate_pos": round(float((g["realized_ret"] > 0).mean()), 3),
        "avg_ret_pct": round(float(g["realized_ret"].mean()) * 100, 2),
    }


def stats(last_days: Optional[int] = None) -> dict[str, Any]:
    """Track record agregat prediksi yang SUDAH dievaluasi."""
    df = _load()
    res: dict[str, Any] = {
        "logged_total": int(len(df)),
        "pending": int((~df["evaluated"].astype(bool)).sum()) if not df.empty else 0,
    }
    if df.empty:
        return {**res, "evaluated": 0}
    ev = df[df["evaluated"].astype(bool)].copy()
    if last_days:
        cutoff = (pd.Timestamp.today() - pd.Timedelta(days=last_days)).date().isoformat()
        ev = ev[ev["date"] >= cutoff]
    res["evaluated"] = int(len(ev))
    if ev.empty:
        return res
    res["date_range"] = [str(ev["date"].min()), str(ev["date"].max())]

    res["by_signal"] = {s: _grp_stats(g) for s, g in ev.groupby("signal")}
    buy = ev[ev["signal"] == "BUY"]
    res["ml_buy_confident"] = _grp_stats(buy[buy["confident"].astype(bool)])
    res["ml_buy_all"] = _grp_stats(buy)

    rule_buy = ev[ev["rule_signal"].isin(RULE_BUYISH)]
    res["rule_buyish"] = _grp_stats(rule_buy)
    res["universe_baseline"] = {
        "n": int(len(ev)),
        "avg_ret_pct": round(float(ev["realized_ret"].mean()) * 100, 2),
    }

    # Kalibrasi: realisasi P(BUY) per keranjang probabilitas
    try:
        bins = pd.cut(ev["p_buy"], [0, .3, .4, .45, .5, .6, 1.0])
        res["calibration_p_buy"] = [
            {"bucket": str(b), "n": int(len(g)),
             "realized_up_rate": round(float((g["outcome"] == 1).mean()), 3),
             "avg_ret_pct": round(float(g["realized_ret"].mean()) * 100, 2)}
            for b, g in ev.groupby(bins, observed=True) if len(g)
        ]
    except Exception:
        pass
    return res


def calibrate() -> dict[str, Any]:
    """Saran ambang confidence BUY dari realisasi (maksimalkan avg return)."""
    df = _load()
    if df.empty:
        return {"ok": False, "reason": "belum ada data"}
    ev = df[df["evaluated"].astype(bool) & (df["signal"] == "BUY")]
    if len(ev) < MIN_SAMPLES_CALIBRATION:
        return {"ok": False, "reason": f"sampel BUY terevaluasi {len(ev)} < {MIN_SAMPLES_CALIBRATION}"}
    best_thr, best_ret, grid = None, None, []
    for thr in (0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        sel = ev[ev["p_buy"] >= thr]
        if len(sel) < 20:
            continue
        avg = float(sel["realized_ret"].mean())
        grid.append({"thr": thr, "n": int(len(sel)), "avg_ret_pct": round(avg * 100, 2),
                     "hit_rate": round(float((sel["outcome"] == 1).mean()), 3)})
        if best_ret is None or avg > best_ret:
            best_thr, best_ret = thr, avg
    if best_thr is None:
        return {"ok": False, "reason": "tidak ada ambang dengan sampel cukup"}
    return {"ok": True, "suggested_conf_threshold": best_thr,
            "avg_ret_pct_at_thr": round(best_ret * 100, 2), "grid": grid}


def _write_summary(df: Optional[pd.DataFrame] = None) -> dict[str, Any]:
    """Tulis ringkasan + ambang terkalibrasi (dibaca ml_signal & API)."""
    summ = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": stats(),
        "stats_90d": stats(last_days=90),
        "calibration": calibrate(),
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summ, ensure_ascii=False, indent=1))
    return summ


def calibrated_threshold() -> Optional[float]:
    """Ambang confidence hasil kalibrasi realisasi (None bila belum layak)."""
    try:
        d = json.loads(SUMMARY.read_text())
        cal = d.get("calibration") or {}
        if cal.get("ok"):
            return float(cal["suggested_conf_threshold"])
    except Exception:
        pass
    return None


def summary_for_api() -> dict[str, Any]:
    try:
        return json.loads(SUMMARY.read_text())
    except Exception:
        return {"updated_at": None, "stats": stats(), "calibration": {"ok": False}}


def summary_for_ai() -> Optional[dict[str, Any]]:
    """Ringkasan padat untuk konteks LLM advisor (None bila belum ada evaluasi)."""
    s = stats(last_days=180)
    if not s.get("evaluated"):
        return None
    return {
        "periode": s.get("date_range"),
        "n_evaluasi": s.get("evaluated"),
        "ml_buy_confident": s.get("ml_buy_confident"),
        "ml_buy_all": s.get("ml_buy_all"),
        "rule_buyish": s.get("rule_buyish"),
        "baseline_universe": s.get("universe_baseline"),
        "catatan": "hit_rate = prediksi arah benar per definisi label; "
                   "win_rate_pos = return realisasi > 0.",
    }


def _fmt_rp(v: Any) -> str:
    try:
        return f"{float(v):,.0f}".replace(",", ".")
    except Exception:
        return "—"


def build_telegram_text(rows: pd.DataFrame, s: dict[str, Any],
                        label: Optional[str] = None) -> str:
    """Susun pesan HTML ringkasan sinyal ML harian (murni dari data)."""
    d = rows["date"].iloc[0] if not rows.empty else date.today().isoformat()
    if label:
        d = f"{d} · {label}"
    n_conf = int(rows["confident"].sum()) if not rows.empty else 0
    lines = [f"🤖 <b>Sinyal ML Harian</b> — {d}",
             f"Mode <b>shadow</b> · horizon 5 hari bursa · {len(rows)} ticker · {n_conf} confident", ""]

    top = rows[rows["signal"] == "BUY"].nlargest(5, "p_buy")
    if not top.empty:
        lines.append("🏆 <b>Top P(BUY)</b>:")
        for i, (_, r) in enumerate(top.iterrows(), 1):
            mark = " ✓" if r["confident"] else ""
            lines.append(f"{i}. <b>{r['ticker']}</b> {r['p_buy']*100:.0f}%{mark} · Rp{_fmt_rp(r['price'])} · rule: {r['rule_signal'] or '—'}")

    sells = rows[rows["signal"] == "SELL"].nlargest(3, "p_sell")
    if not sells.empty:
        lines.append("")
        lines.append("⚠️ <b>Peringatan SELL</b>: " + " · ".join(
            f"{r['ticker']} {r['p_sell']*100:.0f}%" for _, r in sells.iterrows()))

    if s.get("evaluated"):
        mb = s.get("ml_buy_all") or {}
        rb = s.get("rule_buyish") or {}
        lines.append("")
        lines.append(f"📊 <b>Track record</b> ({s['evaluated']} evaluasi): "
                     f"ML BUY win {mb.get('win_rate_pos', 0)*100:.0f}% · avg {mb.get('avg_ret_pct', 0):+.1f}%"
                     + (f" | rule {rb.get('win_rate_pos', 0)*100:.0f}% · {rb.get('avg_ret_pct', 0):+.1f}%" if rb.get("n") else ""))

    lines.append("")
    lines.append("<i>Shadow mode — pembanding terukur, bukan perintah beli. "
                 "Detail: dashboard → panel Sinyal ML.</i>")
    return "\n".join(lines)


def _scan_rows() -> pd.DataFrame:
    """Snapshot prediksi terkini dari scan universe (untuk kiriman intraday).

    rule_signal diambil dari catatan store HARI INI bila ada (funnel penuh
    terlalu berat untuk dijalankan tiap jam kirim).
    """
    from app.core import ml_signal
    scan = ml_signal.scan_universe(force=True, hist_ttl=1200)
    sigs = scan.get("signals") or []
    if not sigs:
        return pd.DataFrame()
    rows = pd.DataFrame(sigs)
    rows["date"] = date.today().isoformat()
    rows["rule_signal"] = None
    st = _load()
    if not st.empty:
        today_rows = st[st["date"] == date.today().isoformat()]
        if not today_rows.empty:
            m = today_rows.set_index("ticker")["rule_signal"]
            rows["rule_signal"] = rows["ticker"].map(m)
    return rows


def telegram_summary(source: str = "store",
                     label: Optional[str] = None) -> dict[str, Any]:
    """Kirim ringkasan sinyal ML ke Telegram.

    source "store" = baris tercatat terakhir (kiriman resmi setelah tutup);
    source "scan"  = snapshot prediksi terkini (kiriman intraday).
    """
    from app.core import telegram_notify
    if not telegram_notify.is_configured():
        return {"ok": False, "error": "Telegram belum dikonfigurasi"}
    if source == "scan":
        rows = _scan_rows()
    else:
        df = _load()
        rows = df[df["date"] == df["date"].max()] if not df.empty else pd.DataFrame()
    if rows.empty:
        return {"ok": False, "error": "belum ada prediksi tersedia"}
    text = build_telegram_text(rows, stats(last_days=180), label=label)
    return telegram_notify.send(text)


def run_daily() -> dict[str, Any]:
    """Dipanggil scheduler tiap sore hari bursa: evaluasi dulu, lalu catat baru."""
    ev = evaluate_matured()
    lg = log_today()
    tg = None
    try:
        from app.config import settings
        if getattr(settings, "ml_track_telegram", False) and (lg.get("ok") or lg.get("skipped")):
            tg = telegram_summary(label="penutupan")
    except Exception as e:  # noqa: BLE001
        tg = {"ok": False, "error": str(e)}
    return {"evaluate": ev, "log": lg, "telegram": tg}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="store_true")
    ap.add_argument("--evaluate", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--telegram", action="store_true", help="kirim ringkasan hari terakhir ke Telegram")
    ap.add_argument("--telegram-scan", action="store_true", help="kirim snapshot prediksi terkini ke Telegram")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.log:
        print(json.dumps(log_today(force=args.force), indent=1))
    if args.evaluate:
        print(json.dumps(evaluate_matured(), indent=1))
    if args.telegram:
        print(json.dumps(telegram_summary(), ensure_ascii=False, indent=1))
    if args.telegram_scan:
        from datetime import datetime as _dt
        print(json.dumps(telegram_summary(source="scan",
                                          label=_dt.now().strftime("%H:%M WIB")),
                         ensure_ascii=False, indent=1))
    if args.report:
        print(json.dumps({"stats": stats(), "calibration": calibrate()},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
