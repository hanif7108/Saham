"""
Snapshot portofolio harian → dataset permanen di datalake.

Setiap sore (16:30 WIB, bersama siklus penutupan) posisi + P/L + vonis exit
+ P(SELL) ML dibekukan ke ml_data/portfolio_snapshots/portfolio_YYYY-MM-DD.json
lalu tersinkron ke NAS predictions/portfolio/. Kegunaan:

  1. Dataset evolusi portofolio (kelak bahan analisis: apakah saran exit
     kami benar? berapa selisih vs andai diikuti mentah-mentah?).
  2. Kurva ekuitas harian → ROI bulan berjalan yang TERUKUR terhadap
     target rotasi (roi_target_monthly_pct, aspirasi 10%/bulan) — bukan
     angka harapan.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from zoneinfo import ZoneInfo

from app.config import settings
from app.ml.data_fetch import ML_DATA_DIR

SNAP_DIR = ML_DATA_DIR / "portfolio_snapshots"
WIB = ZoneInfo("Asia/Jakarta")


def build_review() -> dict[str, Any]:
    """Potret posisi + vonis exit + ML terkini (dipakai snapshot & API)."""
    from app.core import exit_rules, portfolio
    from app.data import provider

    data = portfolio.list_positions()
    rows = data.get("positions") or []
    try:
        from app.core import ml_signal
        scan = {x["ticker"]: x for x in
                (ml_signal.scan_universe().get("signals") or [])}
    except Exception:
        scan = {}

    enriched = []
    for r in rows:
        tk = r.get("ticker") or ""
        try:
            hist = provider.get_history(tk, period="6mo", ttl=14400)
            closes = hist["Close"] if hist is not None and not hist.empty else None
        except Exception:
            closes = None
        ml = scan.get(tk)
        if ml is None:
            try:
                from app.data import provider as _pv
                if not _pv.is_us_ticker(tk):
                    from app.core import ml_signal as _mls
                    pr = _mls.predict(tk)
                    if pr.get("available"):
                        ml = {k: pr[k] for k in
                              ("signal", "p_buy", "p_hold", "p_sell")}
            except Exception:
                ml = None
        verdict = exit_rules.evaluate_exit(
            pnl_pct=r.get("pl_pct"), price=r.get("current_price"),
            peak_price=exit_rules.peak_since(closes, r.get("added_at")),
            avg_price=r.get("avg_price"),
            days_held=exit_rules.days_held_bursa(r.get("added_at")), ml=ml)
        enriched.append({
            "ticker": tk, "broker": r.get("broker"), "lots": r.get("lots"),
            "avg_price": r.get("avg_price"), "current_price": r.get("current_price"),
            "pl_pct": r.get("pl_pct"), "net_pl_pct": r.get("net_pl_pct"),
            "value": r.get("value"), "added_at": r.get("added_at"),
            "exit_action": verdict["action"], "exit_kode": verdict["kode"],
            "exit_alasan": verdict["alasan"],
            "ml_p_sell": (ml or {}).get("p_sell"),
            "ml_p_buy": (ml or {}).get("p_buy"),
        })

    today = datetime.now(WIB).date().isoformat()
    return {"date": today,
            "taken_at": datetime.now(WIB).isoformat(timespec="seconds"),
            "summary": data.get("summary") or {},
            "positions": enriched}


def save_daily() -> dict[str, Any]:
    """Bekukan potret portofolio hari ini (overwrite bila diambil ulang)."""
    snap = build_review()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"portfolio_{snap['date']}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1))
    return {"ok": True, "date": snap["date"], "positions": len(snap["positions"])}


def monthly_roi() -> Optional[dict[str, Any]]:
    """ROI bulan berjalan dari kurva snapshot (basis nilai bersih).

    None bila snapshot pembanding belum ada. Bila basis modal berubah
    (ada beli/jual di tengah), hasil ditandai approx — kurva snapshot
    tetap menjadi sumber kebenaran granular.
    """
    files = sorted(SNAP_DIR.glob("portfolio_*.json"))
    if len(files) < 2:
        return None
    try:
        latest = json.loads(files[-1].read_text())
        cutoff = None
        for f in files:                       # snapshot tertua dalam ~31 hari
            d = json.loads(f.read_text())
            age = (datetime.fromisoformat(latest["date"]).date()
                   - datetime.fromisoformat(d["date"]).date()).days
            if age <= 31:
                cutoff = d
                break
        if not cutoff or cutoff["date"] == latest["date"]:
            return None
        v0 = float(cutoff["summary"].get("total_net_value") or 0)
        v1 = float(latest["summary"].get("total_net_value") or 0)
        c0 = float(cutoff["summary"].get("total_cost") or 0)
        c1 = float(latest["summary"].get("total_cost") or 0)
        if v0 <= 0:
            return None
        roi = (v1 / v0 - 1) * 100
        return {"since": cutoff["date"], "until": latest["date"],
                "roi_pct": round(roi, 2),
                "target_pct": float(getattr(settings, "roi_target_monthly_pct", 10.0)),
                "approx_basis_changed": abs(c1 - c0) > max(1.0, 0.005 * max(c0, 1.0))}
    except Exception:
        return None
