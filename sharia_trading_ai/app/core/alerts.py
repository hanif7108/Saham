"""
Alert — pindai peluang entry (dari funnel) & status posisi portofolio.

Menghasilkan daftar alert + teks ringkas siap kirim ke Telegram.
"""

from __future__ import annotations

from typing import Any

from app.config import MM
from app.core import funnel, portfolio
from app.data import provider


def _market() -> dict[str, Any]:
    idx = provider.get_index_history(period="2y")
    if idx is None or idx.empty or len(idx) < 200:
        return {"trend": "n/a"}
    close = float(idx["Close"].iloc[-1])
    sma = float(idx["Close"].rolling(200).mean().iloc[-1])
    return {"trend": "UPTREND" if close > sma else "DOWNTREND",
            "price": round(close, 2)}


def build_alerts(limit: int = 15) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    mkt = _market()
    alerts.append({"tipe": "market", "urgency": "info",
                   "teks": f"Arah pasar IHSG: {mkt.get('trend')} ({mkt.get('price','-')})"})

    # peluang entry dari funnel
    try:
        scr = funnel.screen_universe(min_magic=0, min_canslim=0, limit=limit)
        for s in scr["hasil"]:
            if s.get("css") == "buy" or s.get("entry_signals"):
                alerts.append({
                    "tipe": "entry", "urgency": "buy", "ticker": s["ticker"],
                    "teks": f"{s['ticker']}: {s['aksi']} · sinyal {','.join(s['entry_signals']) or '-'} "
                            f"· 6M {s['magic_score']}/6 · CS {s['canslim_score']}/7 · skor {s['skor']}",
                })
    except Exception:
        pass

    # status portofolio
    try:
        port = portfolio.list_positions()
        for p in port["positions"]:
            if p.get("pl_pct") is None:
                continue
            if p["pl_pct"] >= MM.PROFIT_FUND_PCT:
                alerts.append({"tipe": "profit", "urgency": "buy", "ticker": p["ticker"],
                               "teks": f"{p['ticker']}: +{p['pl_pct']}% — pertimbangkan take profit (target {MM.PROFIT_FUND_PCT}%)"})
            elif p["pl_pct"] <= -MM.LOSS_FUND_PCT:
                alerts.append({"tipe": "loss", "urgency": "sell", "ticker": p["ticker"],
                               "teks": f"{p['ticker']}: {p['pl_pct']}% — mendekati/lewati cut loss (-{MM.LOSS_FUND_PCT}%)"})
    except Exception:
        pass

    return {"jumlah": len(alerts), "alerts": alerts, "market": mkt}


def format_message(data: dict[str, Any]) -> str:
    lines = ["<b>☪ Sharia Trading AI — Alert</b>"]
    icon = {"market": "📊", "entry": "🟢", "profit": "💰", "loss": "🔴", "info": "ℹ️"}
    for a in data["alerts"]:
        lines.append(f"{icon.get(a['tipe'], '•')} {a['teks']}")
    lines.append("\n<i>Advisory only — bukan ajakan jual/beli. Transaksi tunai (syariah).</i>")
    return "\n".join(lines)
