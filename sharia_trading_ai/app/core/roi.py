"""
ROI portofolio integral + jurnal transaksi + STRATEGI ADAPTIF berbasis ROI.

Tujuan: mengukur Return on Investment menyeluruh (realized + unrealized) dan
MEMAKAI data itu agar algoritma keputusan makin selektif demi mencapai target
profit (default 6% bersih).

  - Jurnal transaksi tertutup → ROI nyata per trade (sudah hitung biaya beli+jual).
  - realized_stats(): win-rate, ROI rata-rata, ROI kumulatif.
  - portfolio_roi(): gabungan realized + unrealized = ROI integral vs target.
  - adaptive_strategy(): bila ROI di bawah target → naikkan ambang AKURASI BELI
    (lebih selektif) → dorong hasil menuju target. Transparan & dapat diaudit.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from app.config import MM, BASE_DIR
from app.core import accounts, portfolio

STORE = BASE_DIR.parent / "data_store" / "trades.json"
STORE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> list[dict[str, Any]]:
    if not STORE.exists():
        return []
    try:
        return json.loads(STORE.read_text())
    except Exception:  # noqa: BLE001
        return []


def _save(rows: list[dict[str, Any]]) -> None:
    STORE.write_text(json.dumps(rows, ensure_ascii=False, indent=2))


def list_trades() -> list[dict[str, Any]]:
    return _load()


def record_trade(ticker: str, lots: int, avg_price: float, exit_price: float,
                 broker: Optional[str] = None, opened: Optional[str] = None,
                 closed: Optional[str] = None, context: Optional[str] = None) -> dict[str, Any]:
    """Catat 1 transaksi tertutup → ROI bersih (termasuk biaya beli+jual broker)."""
    ticker = ticker.upper().strip()
    shares = int(lots) * MM.SHARES_PER_LOT
    fee_buy, fee_sell = accounts.fees_for(broker)
    cost = shares * float(avg_price) * (1 + fee_buy / 100)        # modal riil (incl. biaya beli)
    proceeds = shares * float(exit_price) * (1 - fee_sell / 100)  # hasil bersih (incl. biaya jual)
    roi_idr = proceeds - cost
    roi_pct = (roi_idr / cost * 100) if cost else 0.0
    rows = _load()
    rec = {
        "id": max((r["id"] for r in rows), default=0) + 1,
        "ticker": ticker, "broker": broker, "lots": int(lots),
        "avg_price": float(avg_price), "exit_price": float(exit_price),
        "cost": round(cost), "proceeds": round(proceeds),
        "roi_idr": round(roi_idr), "roi_pct": round(roi_pct, 2),
        "win": roi_idr > 0, "opened": opened,
        "closed": closed or datetime.now().isoformat(timespec="seconds"), "context": context,
    }
    rows.append(rec)
    _save(rows)
    return rec


def delete_trade(trade_id: int) -> bool:
    rows = _load()
    new = [r for r in rows if r["id"] != trade_id]
    if len(new) == len(rows):
        return False
    _save(new)
    return True


# --------------------------- statistik realized --------------------------- #
def realized_stats() -> dict[str, Any]:
    trades = _load()
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "win_rate": None, "avg_roi": None, "realized_roi_pct": None,
                "total_cost": 0, "total_roi_idr": 0, "best": None, "worst": None}
    wins = sum(1 for t in trades if t.get("win"))
    total_cost = sum(t["cost"] for t in trades)
    total_roi_idr = sum(t["roi_idr"] for t in trades)
    rois = [t["roi_pct"] for t in trades]
    return {
        "n_trades": n,
        "win_rate": round(wins / n * 100, 1),
        "avg_roi": round(sum(rois) / n, 2),                          # ROI rata-rata per trade
        "realized_roi_pct": round(total_roi_idr / total_cost * 100, 2) if total_cost else 0,
        "total_cost": round(total_cost), "total_roi_idr": round(total_roi_idr),
        "best": round(max(rois), 2), "worst": round(min(rois), 2),
    }


# --------------------------- equity curve (ROI dari waktu ke waktu) --------------------------- #
def equity_curve() -> list[dict[str, Any]]:
    """Kurva ROI kumulatif (realized) berurut waktu tutup — untuk grafik progres ke target."""
    trades = sorted(_load(), key=lambda t: (t.get("closed") or "", t["id"]))
    pts, cum_pl, cum_cost = [], 0.0, 0.0
    for i, t in enumerate(trades, 1):
        cum_pl += t["roi_idr"]
        cum_cost += t["cost"]
        pts.append({
            "n": i, "date": t.get("closed"), "ticker": t["ticker"],
            "roi_pct": t["roi_pct"], "cum_pl": round(cum_pl),
            "cum_roi_pct": round(cum_pl / cum_cost * 100, 2) if cum_cost else 0.0,
        })
    return pts


# --------------------------- ROI integral portofolio --------------------------- #
def portfolio_roi(target: Optional[float] = None) -> dict[str, Any]:
    target = float(target if target is not None else MM.PROFIT_FUND_PCT)
    s = portfolio.list_positions()["summary"]
    un_invested = s.get("total_modal") or 0                          # modal posisi terbuka (incl. fee beli)
    un_pl = s.get("total_net_pl") or 0                               # P/L bersih (incl. fee jual estimasi)
    un_roi = s.get("total_net_pl_pct") or 0
    rs = realized_stats()
    re_invested = rs["total_cost"]
    re_pl = rs["total_roi_idr"]

    tot_invested = un_invested + re_invested
    tot_pl = un_pl + re_pl
    integral_roi = round(tot_pl / tot_invested * 100, 2) if tot_invested else 0
    return {
        "target_pct": target,
        "integral": {"roi_pct": integral_roi, "pl": round(tot_pl), "invested": round(tot_invested)},
        "unrealized": {"roi_pct": un_roi, "pl": round(un_pl), "invested": round(un_invested)},
        "realized": {"roi_pct": rs["realized_roi_pct"], "pl": re_pl, "invested": re_invested,
                     "n_trades": rs["n_trades"], "win_rate": rs["win_rate"], "avg_roi": rs["avg_roi"]},
        "gap_to_target": round(target - integral_roi, 2),
        "on_track": integral_roi >= target,
    }


# --------------------------- strategi ADAPTIF (AI pakai ROI) --------------------------- #
def _simulation_learning() -> Optional[dict[str, Any]]:
    """Statistik SIMULASI eksekusi (paper trading) — cadangan learning saat
    data realized masih sedikit. Lazy import agar bebas siklus impor."""
    try:
        from app.core import simulation
        s = simulation.stats(with_live=False)["summary"]
        return s if s["n_closed"] >= 3 else None
    except Exception:  # noqa: BLE001
        return None


def adaptive_strategy(target: Optional[float] = None) -> dict[str, Any]:
    """Setel ambang strategi dari kinerja ROI nyata → kejar target profit.
    Bila transaksi realized < 3, pakai track-record SIMULASI sebagai dasar."""
    target = float(target if target is not None else MM.PROFIT_FUND_PCT)
    rs = realized_stats()
    n = rs["n_trades"]
    notes: list[str] = []

    if n < 3:
        sim = _simulation_learning()
        if sim:
            # cold-start TERINFORMASI: belajar dari simulasi paper-trade harian
            sim_avg = sim["avg_roi"] or 0
            sim_wr = sim["win_rate"] or 0
            if sim_avg < target:
                gap = target - sim_avg
                min_acc = min(70.0, 35.0 + gap * 2)
                notes.append(f"Belajar dari SIMULASI ({sim['n_closed']} sinyal): ROI {sim_avg:.1f}% "
                             f"< target {target:.0f}% → ambang akurasi BELI {min_acc:.0f}% (lebih selektif).")
            else:
                min_acc = 35.0
                notes.append(f"Belajar dari SIMULASI ({sim['n_closed']} sinyal): ROI {sim_avg:.1f}% "
                             f"≥ target {target:.0f}% → ambang {min_acc:.0f}%.")
            if sim_wr < 50:
                min_acc = max(min_acc, 50.0)
                notes.append(f"Win-rate simulasi {sim_wr:.0f}% < 50% → ambang dinaikkan ke {min_acc:.0f}% "
                             "(utamakan akurasi tinggi).")
            notes.append("Catatan: ambang dari simulasi otomatis (tab Simulasi); akan digantikan "
                         "data realized setelah ≥3 transaksi nyata tutup.")
            return {"target_pct": target, "min_buy_accuracy": round(min_acc, 1),
                    "take_profit_net_pct": round(target, 2), "based_on_trades": n,
                    "based_on_simulations": sim["n_closed"],
                    "realized_roi_pct": rs["realized_roi_pct"], "notes": notes}
        min_acc = 25.0                                               # cold-start longgar
        notes.append("Belum cukup data realized (<3 transaksi tutup) & simulasi → ambang akurasi dasar 25%. "
                     "Tutup posisi via tombol Jual agar ROI tercatat & strategi mulai belajar.")
    else:
        realized = rs["avg_roi"] or 0
        if realized < target:
            gap = target - realized
            min_acc = min(70.0, 40.0 + gap * 2)                      # makin jauh dari target → makin ketat
            notes.append(f"ROI realized {realized:.1f}% < target {target:.0f}% → ambang akurasi BELI "
                         f"dinaikkan ke {min_acc:.0f}% (lebih selektif, kejar 6%).")
        else:
            min_acc = 40.0
            notes.append(f"ROI realized {realized:.1f}% ≥ target {target:.0f}% → ambang {min_acc:.0f}% (pertahankan).")
        if (rs["win_rate"] or 0) < 50:
            min_acc = max(min_acc, 50.0)
            notes.append(f"Win-rate {rs['win_rate']:.0f}% < 50% → prioritaskan akurasi tinggi & disiplin cut-loss.")

    return {
        "target_pct": target,
        "min_buy_accuracy": round(min_acc, 1),
        "take_profit_net_pct": round(target, 2),
        "based_on_trades": n,
        "realized_roi_pct": rs["realized_roi_pct"],
        "notes": notes,
    }
