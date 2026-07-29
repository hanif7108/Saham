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
from zoneinfo import ZoneInfo

import pandas as pd

from app.ml.data_fetch import ML_DATA_DIR

WIB = ZoneInfo("Asia/Jakarta")


def now_wib() -> datetime:
    """Waktu sekarang dalam WIB (Asia/Jakarta) — bebas dari zona waktu OS."""
    return datetime.now(WIB)


def today_wib() -> date:
    return now_wib().date()

STORE = ML_DATA_DIR / "ml_track.parquet"
SUMMARY = ML_DATA_DIR / "ml_track_summary.json"
INTRADAY_SNAPSHOT = ML_DATA_DIR / "intraday_snapshot.json"
INTRADAY_SCANS = ML_DATA_DIR / "intraday_scans.parquet"

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
    today = today_wib()
    from app.config import settings as _st
    cur_h = int(getattr(_st, "ml_horizon", 10) or 10)
    df = _load()
    if not df.empty and not force and (
        (df["date"] == today.isoformat()) & (df["horizon"] == cur_h)).any():
        return {"ok": True, "skipped": "sudah tercatat", "date": today.isoformat(),
                "horizon": cur_h}
    if not force and not _is_market_data_final(today):
        return {"ok": False, "skipped": "bar penutupan hari ini belum final/bukan hari bursa"}

    if ranking is None:
        from app.core import decisions
        ranking = decisions.build_ranking()

    from app.data import provider
    try:
        from app.core import ml_signal as _mls
        scan_by_tk = {s["ticker"]: s for s in
                      (_mls.scan_universe().get("signals") or [])}
    except Exception:
        scan_by_tk = {}
    idx_rank = [s for s in ranking if not provider.is_us_ticker(s.get("ticker") or "")]
    focus_set = {s["ticker"] for s in sorted(
        idx_rank, key=lambda r: float(r.get("skor") or 0), reverse=True)[:10]}
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
            "in_focus": tk in focus_set,
            "rank_score": (scan_by_tk.get(tk) or {}).get("rank_score"),
            "ens_score": (scan_by_tk.get(tk) or {}).get("ens_score"),
            "veto_sell": (scan_by_tk.get(tk) or {}).get("veto_sell"),
            "rule_signal": s.get("final_signal"),
            "rule_skor": float(s.get("skor") or 0),
            "rule_keputusan": s.get("keputusan"),
            "evaluated": False,
            "eval_date": None,
            "realized_ret": None,
            "outcome": None,
            "ml_correct": None,
            "logged_at": now_wib().isoformat(timespec="seconds"),
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
        cutoff = (pd.Timestamp(now_wib().date()) - pd.Timedelta(days=last_days)).date().isoformat()
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
    if "in_focus" in ev.columns:
        foc = ev[ev["in_focus"].fillna(False).astype(bool)]
        res["focus_top10_all"] = _grp_stats(foc)
        res["focus_top10_ml_buy"] = _grp_stats(foc[foc["signal"] == "BUY"])
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
        "updated_at": now_wib().isoformat(timespec="seconds"),
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


def _morning_market_lines() -> list[str]:
    """Rekap pasar H-1 untuk briefing pagi (08:30, sebelum bursa buka 09:00)."""
    lines: list[str] = []
    try:
        from app.data import provider
        idx = provider.get_index_history(period="1y")
        c = idx["Close"].dropna()
        if len(c) >= 2:
            last, prev = float(c.iloc[-1]), float(c.iloc[-2])
            chg = (last / prev - 1) * 100
            arrow = "🟢" if chg >= 0 else "🔴"
            sma200 = float(c.rolling(200).mean().iloc[-1])
            ma20 = float(c.rolling(20).mean().iloc[-1])
            ma60 = float(c.rolling(60).mean().iloc[-1])
            regime = "BULLISH" if ma20 > ma60 * 1.01 else (
                "BEARISH" if ma20 < ma60 * 0.99 else "NETRAL")
            pos200 = "di atas" if last > sma200 else "di bawah"
            lines += [f"🌅 <b>Rekap pasar kemarin</b> ({str(c.index[-1])[:10]}):",
                      f"{arrow} IHSG {last:,.0f} ({chg:+.2f}%) · {pos200} SMA200 "
                      f"({sma200:,.0f}) · regime <b>{regime}</b>"]
    except Exception:
        pass
    try:
        from app.data import provider
        sp = provider.get_history("^GSPC", period="10d", ttl=14400)["Close"].dropna()
        if len(sp) >= 2:
            chg = (float(sp.iloc[-1]) / float(sp.iloc[-2]) - 1) * 100
            arrow = "🟢" if chg >= 0 else "🔴"
            lines.append(f"{arrow} S&P 500 {float(sp.iloc[-1]):,.0f} ({chg:+.2f}%) "
                         f"— sentimen global semalam")
    except Exception:
        pass
    if lines:
        lines.append("")
    return lines


def _positions_lines() -> list[str]:
    """Bagian '📁 Posisi Anda' utk pesan Telegram: P/L + saran exit per aset.

    Kosong bila portofolio belum diisi. ML hanya utk saham IDX; saham US
    (Pluang) dinilai aturan harga saja (SL/TP/trailing/time-stop).
    """
    try:
        from app.core import exit_rules, portfolio
        from app.data import provider
        data = portfolio.list_positions()
        rows = data.get("positions") or []
        if not rows:
            return []
        try:
            from app.core import ml_signal as _mls
            scan_by_tk = {x["ticker"]: x for x in
                          (_mls.scan_universe().get("signals") or [])}
        except Exception:
            scan_by_tk = {}
        lines = ["", "📁 <b>Posisi Anda</b>:"]
        for r in rows[:12]:
            tk = r.get("ticker") or ""
            try:
                hist = provider.get_history(tk, period="6mo", ttl=14400)
                closes = hist["Close"] if hist is not None and not hist.empty else None
            except Exception:
                closes = None
            peak = exit_rules.peak_since(closes, r.get("added_at"))
            days = exit_rules.days_held_bursa(r.get("added_at"))
            ml = scan_by_tk.get(tk)
            if ml is None and not provider.is_us_ticker(tk):
                # aset milik WAJIB selalu dapat prediksi ML (walau di luar
                # filter scan / universe tampilan) — prediksi langsung
                try:
                    from app.core import ml_signal as _mls2
                    pr = _mls2.predict(tk)
                    if pr.get("available"):
                        ml = {k: pr[k] for k in
                              ("signal", "p_buy", "p_hold", "p_sell")}
                except Exception:
                    ml = None
            v = exit_rules.evaluate_exit(
                pnl_pct=r.get("pl_pct"), price=r.get("current_price"),
                peak_price=peak, avg_price=r.get("avg_price"),
                days_held=days, ml=ml)
            icon = {"SELL": "🔴", "TRAIL": "🟠", "WASPADA": "🟡", "HOLD": "🟢"}.get(v["action"], "⚪")
            pl = r.get("pl_pct")
            pl_txt = f"{pl:+.1f}%" if pl is not None else "—"
            broker = f" [{r['broker']}]" if r.get("broker") else ""
            hari = f" · {days}h" if days is not None else ""
            mltxt = (f" · ML {ml.get('signal','—')}: P(SELL) "
                     f"{float(ml['p_sell']):.0%} / P(BUY) {float(ml['p_buy']):.0%}"
                     ) if ml else " · ML: n/a (saham US — aturan harga saja)"
            lines.append(f"{icon} <b>{tk}</b>{broker} {pl_txt}{hari} → "
                         f"<b>{v['action']}</b>: {v['alasan']}{mltxt}")
        try:
            from app.core import portfolio_snapshot
            roi = portfolio_snapshot.monthly_roi()
            tgt = None
            if roi:
                note = " (basis berubah — approx)" if roi.get("approx_basis_changed") else ""
                emoji = "🎯" if roi["roi_pct"] >= roi["target_pct"] else "📉"
                lines.append(f"{emoji} ROI {roi['since']}→{roi['until']}: "
                             f"<b>{roi['roi_pct']:+.2f}%</b> vs target "
                             f"{roi['target_pct']:.0f}%/bln{note}")
            else:
                from app.config import settings as _st3
                tgt = float(getattr(_st3, "roi_target_monthly_pct", 10.0))
                lines.append(f"🎯 Target rotasi {tgt:.0f}%/bln — ROI terukur mulai "
                             f"tersedia setelah beberapa snapshot harian.")
        except Exception:
            pass
        lines.append("<i>Saran advisory — eksekusi & risiko di tangan Anda.</i>")
        return lines
    except Exception:
        return []


def build_telegram_text(rows: pd.DataFrame, s: dict[str, Any],
                        label: Optional[str] = None) -> str:
    """Susun pesan HTML ringkasan sinyal ML harian (murni dari data)."""
    d = rows["date"].iloc[0] if not rows.empty else today_wib().isoformat()
    if label:
        d = f"{d} · {label}"
    n_conf = int(rows["confident"].sum()) if not rows.empty else 0
    h = int(rows["horizon"].iloc[0]) if ("horizon" in rows.columns and not rows.empty) else 10
    judul = "🌅 <b>Briefing Pagi</b>" if (label or "").startswith("08:30") \
        else "🤖 <b>Sinyal ML Harian</b>"
    lines = [f"{judul} — {d}",
             f"Mode <b>shadow</b> · horizon {h} hari bursa · {len(rows)} ticker · {n_conf} confident", ""]
    if (label or "").startswith("08:30"):
        lines.extend(_morning_market_lines())

    # Urutan produksi = p_buy classifier (konfigurasi terbaik pada backtest
    # sadar-biaya); veto SELL tetap disaring sebagai pengaman.
    cand = rows[rows["signal"] == "BUY"]
    if "veto_sell" in rows.columns:
        cand = cand[~cand["veto_sell"].fillna(False).astype(bool)]
    if "price" in cand.columns:
        from app.config import settings as _st2
        min_p = float(getattr(_st2, "ml_min_price", 500) or 0)
        cand = cand[cand["price"].fillna(0) >= min_p]
    top = cand.nlargest(5, "p_buy")
    if not top.empty:
        lines.append("🏆 <b>Top pilihan ML</b> (urut P(BUY), veto SELL disaring):")
        for i, (_, r) in enumerate(top.iterrows(), 1):
            mark = " ✓" if r["confident"] else ""
            lines.append(f"{i}. <b>{r['ticker']}</b> {r['p_buy']*100:.0f}%{mark} · Rp{_fmt_rp(r['price'])} · rule: {r['rule_signal'] or '—'}")

    sells = rows[rows["signal"] == "SELL"].nlargest(3, "p_sell")
    if not sells.empty:
        lines.append("")
        lines.append("⚠️ <b>Peringatan SELL</b>: " + " · ".join(
            f"{r['ticker']} {r['p_sell']*100:.0f}%" for _, r in sells.iterrows()))

    if "price" in rows.columns and rows["price"].notna().any():
        lines.extend(_closing_comparison_lines(rows))

    lines.extend(_positions_lines())

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
    rows["date"] = today_wib().isoformat()
    if "horizon" not in rows.columns:
        from app.config import settings as _st
        rows["horizon"] = int(getattr(_st, "ml_horizon", 10) or 10)
    rows["rule_signal"] = None
    st = _load()
    if not st.empty:
        today_rows = st[st["date"] == today_wib().isoformat()]
        if not today_rows.empty:
            m = today_rows.set_index("ticker")["rule_signal"]
            rows["rule_signal"] = rows["ticker"].map(m)
    return rows


def _save_intraday_snapshot(rows: pd.DataFrame, label: Optional[str]) -> None:
    """Simpan Top-5 BUY (>= harga minimum) + harga saat kiriman intraday.

    Dibaca pesan penutupan untuk menampilkan "harga saat sinyal vs penutupan"
    (permintaan 2026-07-28: akurasi intraday terlihat langsung)."""
    try:
        from app.config import settings as _st
        min_p = float(getattr(_st, "ml_min_price", 500) or 0)
        cand = rows[(rows["signal"] == "BUY") & (rows["price"].fillna(0) >= min_p)]
        top = cand.nlargest(5, "p_buy")
        if top.empty:
            return
        INTRADAY_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        INTRADAY_SNAPSHOT.write_text(json.dumps({
            "date": today_wib().isoformat(),
            "label": label or now_wib().strftime("%H:%M WIB"),
            "picks": [{"ticker": r["ticker"], "price": float(r["price"]),
                       "p_buy": float(r["p_buy"])} for _, r in top.iterrows()],
        }, ensure_ascii=False, indent=1))
    except Exception:
        pass


def _append_intraday_scan(rows: pd.DataFrame, label: Optional[str]) -> None:
    """Arsipkan SELURUH prediksi scan intraday (append, permanen).

    Ini datalake mikro-struktur: probabilitas semua ticker pada beberapa
    titik waktu intraday + (kelak) realisasi harga = bahan training untuk
    perbaikan akurasi berikutnya. Ikut tersinkron ke NAS tiap sore.
    """
    try:
        snap = rows.copy()
        snap["scan_label"] = label or now_wib().strftime("%H:%M WIB")
        snap["scanned_at"] = now_wib().isoformat(timespec="seconds")
        keep = [c for c in ("date", "scan_label", "scanned_at", "ticker",
                            "signal", "p_buy", "p_hold", "p_sell", "confident",
                            "price", "horizon") if c in snap.columns]
        snap = snap[keep]
        if INTRADAY_SCANS.exists():
            snap = pd.concat([pd.read_parquet(INTRADAY_SCANS), snap],
                             ignore_index=True)
        tmp = INTRADAY_SCANS.with_suffix(".tmp.parquet")
        snap.to_parquet(tmp)
        os.replace(tmp, INTRADAY_SCANS)
    except Exception:
        pass


def _closing_comparison_lines(close_rows: pd.DataFrame) -> list[str]:
    """Baris 'harga saat sinyal intraday -> penutupan' utk pesan penutupan."""
    try:
        snap = json.loads(INTRADAY_SNAPSHOT.read_text())
    except Exception:
        return []
    if snap.get("date") != today_wib().isoformat() or not snap.get("picks"):
        return []
    close_by_tk = dict(zip(close_rows["ticker"], close_rows["price"]))
    lines = [f"", f"📍 <b>Sinyal {snap['label']} → penutupan</b>:"]
    for pk in snap["picks"]:
        tk, p0 = pk["ticker"], float(pk["price"])
        p1 = close_by_tk.get(tk)
        if not p1 or p0 <= 0:
            continue
        chg = (float(p1) / p0 - 1) * 100
        arrow = "✅" if chg > 0 else ("➖" if chg == 0 else "❌")
        lines.append(f"• {tk} Rp{_fmt_rp(p0)} → Rp{_fmt_rp(p1)} ({chg:+.2f}%) {arrow}")
    return lines if len(lines) > 2 else []


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
        _save_intraday_snapshot(rows, label)
        _append_intraday_scan(rows, label)
    else:
        df = _load()
        rows = df[df["date"] == df["date"].max()] if not df.empty else pd.DataFrame()
        if not rows.empty and "horizon" in rows.columns:
            from app.config import settings as _st
            cur_h = int(getattr(_st, "ml_horizon", 10) or 10)
            cur = rows[rows["horizon"] == cur_h]
            if not cur.empty:
                rows = cur          # hari transisi: pakai batch horizon aktif
    if rows.empty:
        return {"ok": False, "error": "belum ada prediksi tersedia"}
    text = build_telegram_text(rows, stats(last_days=180), label=label)
    res = telegram_notify.send(text)
    if res.get("ok"):
        try:
            _send_narrative(rows, label)
        except Exception:  # noqa: BLE001
            pass
    return res


def _send_narrative(rows: pd.DataFrame, label: Optional[str]) -> None:
    """Pesan ke-2: narasi & pembelajaran 3 pilihan teratas sesi ini."""
    from app.config import settings as _st
    if not getattr(_st, "ml_narrative_telegram", True):
        return
    from app.core import telegram_notify
    from app.ml import narrator
    cand = rows[rows["signal"] == "BUY"].copy()
    if "veto_sell" in cand.columns:
        cand = cand[~cand["veto_sell"].fillna(False).astype(bool)]
    if "price" in cand.columns:
        min_p = float(getattr(_st, "ml_min_price", 500) or 0)
        cand = cand[cand["price"].fillna(0) >= min_p]
    top = cand.nlargest(3, "p_buy")
    picks = [{"ticker": r["ticker"], "name": r.get("name"),
              "price": r.get("price"),
              "rule_signal": r.get("rule_signal")} for _, r in top.iterrows()]
    text = narrator.build_narrative(picks, label)
    if text:
        telegram_notify.send(text)


def run_daily() -> dict[str, Any]:
    """Dipanggil scheduler tiap sore hari bursa: evaluasi dulu, lalu catat baru."""
    ev = evaluate_matured()
    lg = log_today()
    try:
        from app.core import portfolio_snapshot
        portfolio_snapshot.save_daily()
    except Exception:  # noqa: BLE001
        pass
    tg = None
    try:
        from app.config import settings
        if getattr(settings, "ml_track_telegram", False) and (lg.get("ok") or lg.get("skipped")):
            tg = telegram_summary(label=f"penutupan · {now_wib().strftime('%H:%M WIB')}")
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
        print(json.dumps(telegram_summary(source="scan",
                                          label=now_wib().strftime("%H:%M WIB")),
                         ensure_ascii=False, indent=1))
    if args.report:
        print(json.dumps({"stats": stats(), "calibration": calibrate()},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
