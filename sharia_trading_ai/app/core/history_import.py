"""
Rekonsiliasi RIWAYAT TRANSAKSI broker (Order History / Mutasi).

Mengubah daftar transaksi (BUY/SELL/DEPOSIT/WITHDRAW) menjadi:
  - transaksi TERTUTUP (BUY↔SELL dicocokkan FIFO) → ROI nyata utk jurnal,
  - POSISI TERBUKA (lot beli yang belum terjual) → posisi portofolio,
  - ALIRAN KAS (deposit/withdraw/beli/jual) → saldo cash perkiraan.

Dipakai agar pengguna cukup unggah screenshot/PDF riwayat → jurnal ROI & posisi
terisi otomatis (data training untuk strategi adaptif terus mengalir).
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import MM
from app.core import accounts, portfolio, roi


def reconcile(transactions: list[dict], broker: Optional[str]) -> dict[str, Any]:
    broker = broker or "Profits Anywhere"
    fee_buy, fee_sell = accounts.fees_for(broker)
    # Riwayat broker = NEWEST-FIRST. Balik dulu (jadi kronologis: BELI sebelum JUAL
    # pada hari yang sama), lalu STABLE-sort tanggal naik → FIFO benar.
    txns = sorted(transactions[::-1], key=lambda t: (t.get("date") or "0000"))

    open_lots: dict[str, list[list]] = {}            # ticker → [[price, lots, date], ...] FIFO
    closed: list[dict] = []
    flow = {"deposit": 0.0, "withdraw": 0.0, "buy_net": 0.0, "sell_net": 0.0}

    for t in txns:
        act, tk = t.get("action"), t.get("ticker")
        net = t.get("net") or 0
        if act == "DEPOSIT":
            flow["deposit"] += net
        elif act == "WITHDRAW":
            flow["withdraw"] += net
        elif act == "BUY" and tk and t.get("lots"):
            open_lots.setdefault(tk, []).append([t["price"], int(t["lots"]), t.get("date")])
            flow["buy_net"] += net
        elif act == "SELL" and tk and t.get("lots"):
            flow["sell_net"] += net
            remaining = int(t["lots"])
            q = open_lots.get(tk, [])
            while remaining > 0 and q:
                bp, bl, bd = q[0]
                used = min(remaining, bl)
                closed.append({"ticker": tk, "lots": used, "avg_price": bp,
                               "exit_price": t["price"], "opened": bd, "closed": t.get("date")})
                remaining -= used
                if used >= bl:
                    q.pop(0)
                else:
                    q[0][1] = bl - used
            # remaining>0 → jual > beli (riwayat tak lengkap) → sisa diabaikan

    # ROI bersih tiap transaksi tertutup (termasuk biaya beli+jual)
    sh = MM.SHARES_PER_LOT
    for c in closed:
        shares = c["lots"] * sh
        cost = shares * c["avg_price"] * (1 + fee_buy / 100)
        proceeds = shares * c["exit_price"] * (1 - fee_sell / 100)
        c["roi_idr"] = round(proceeds - cost)
        c["roi_pct"] = round((proceeds - cost) / cost * 100, 2) if cost else 0.0

    open_positions = []
    for tk, q in open_lots.items():
        lots = sum(l for _, l, _ in q)
        if lots <= 0:
            continue
        avg = sum(p * l for p, l, _ in q) / lots
        open_positions.append({"ticker": tk, "lots": lots, "avg_price": round(avg, 2)})

    bal = flow["deposit"] - flow["withdraw"] + flow["sell_net"] - flow["buy_net"]
    realized_idr = sum(c["roi_idr"] for c in closed)
    realized_cost = sum(c["lots"] * sh * c["avg_price"] * (1 + fee_buy / 100) for c in closed)
    return {
        "broker": broker, "n_transactions": len(txns),
        "closed_trades": closed, "open_positions": open_positions,
        "cash_flow": {**{k: round(v) for k, v in flow.items()}, "computed_balance": round(bal)},
        "realized": {"n": len(closed), "roi_idr": round(realized_idr),
                     "roi_pct": round(realized_idr / realized_cost * 100, 2) if realized_cost else None,
                     "wins": sum(1 for c in closed if c["roi_idr"] > 0)},
        "fee_buy_pct": fee_buy, "fee_sell_pct": fee_sell,
    }


def _sig(c: dict) -> tuple:
    return (c["ticker"], round(c["avg_price"], 2), round(c["exit_price"], 2),
            c["lots"], (c.get("closed") or "")[:10])      # tanggal saja (abaikan jam) utk anti-dobel


def apply(transactions: list[dict], broker: Optional[str],
          set_cash: bool = True, replace_positions: bool = True) -> dict[str, Any]:
    """Terapkan rekonsiliasi: catat trade tertutup (anti-dobel), perbarui posisi & cash."""
    rec = reconcile(transactions, broker)
    broker = rec["broker"]

    existing = {_sig(t) for t in roi.list_trades()
                if t.get("ticker") and t.get("exit_price")}
    recorded = []
    for c in rec["closed_trades"]:
        if _sig(c) in existing:
            continue                                   # hindari dobel bila diimpor ulang
        closed = (c["closed"] + "T15:00:00") if c.get("closed") else None
        roi.record_trade(c["ticker"], c["lots"], c["avg_price"], c["exit_price"],
                         broker=broker, opened=c.get("opened"), closed=closed, context="history_import")
        recorded.append(c["ticker"])
        existing.add(_sig(c))

    pos_changed = False
    if replace_positions:
        for p in portfolio.list_positions()["positions"]:
            if p.get("broker") == broker:
                portfolio.remove_position(p["id"])
        for op in rec["open_positions"]:
            portfolio.add_position(op["ticker"], op["lots"], op["avg_price"], broker)
        pos_changed = True

    bal = rec["cash_flow"]["computed_balance"]
    cash_set = False
    cash_warning = None
    if set_cash and bal >= 0:
        accounts.set_account(broker, bal)
        cash_set = True
    elif set_cash:
        cash_warning = (f"Saldo terhitung negatif (Rp {bal:,}) → riwayat mungkin TAK LENGKAP "
                        "(ada deposit/withdraw lama tak tercakup). Cash tidak diubah; isi manual."
                        ).replace(",", ".")

    return {**rec, "recorded_trades": recorded, "positions_replaced": pos_changed,
            "cash_set": cash_set, "cash_warning": cash_warning}
