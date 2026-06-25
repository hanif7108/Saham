"""Endpoint screening — universe, kepatuhan syariah, dan funnel."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core import funnel, sharia_screening
from app.data import provider

from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

router = APIRouter(prefix="/api", tags=["screening"])


@router.get("/universe")
def universe():
    """Daftar saham syariah (seed DES/ISSI)."""
    rows = provider.get_universe()
    return {"jumlah": len(rows), "saham": rows}


@router.get("/market")
def market():
    """Status arah pasar (IHSG vs SMA200) — komponen M dari CAN SLIM."""
    import math
    idx = provider.get_index_history(period="2y")
    if idx is None or idx.empty or len(idx) < 200:
        return {"ok": False}
    close = float(idx["Close"].iloc[-1])
    prev = float(idx["Close"].iloc[-2])
    sma200 = float(idx["Close"].rolling(200).mean().iloc[-1])
    
    # Tangani NaN secara defensif
    close_val = round(close, 2) if not math.isnan(close) else 0.0
    
    # Untuk persentase perubahan IHSG harian, gunakan previousClose dari fast_info jika tersedia
    # guna menghindari kesalahan persentase akibat data hari sebelumnya yang terlewat (missed) di yfinance.
    prev_val = 0.0
    try:
        yf_ticker = provider._ticker(provider.INDEX_TICKER)
        prev_close = yf_ticker.fast_info.get("previousClose")
        if prev_close is not None and not math.isnan(prev_close) and prev_close > 0:
            prev_val = round(float(prev_close), 2)
    except Exception:
        pass
        
    if not prev_val:
        prev_val = round(prev, 2) if not math.isnan(prev) else 0.0
        
    sma200_val = round(sma200, 2) if not math.isnan(sma200) else 0.0
    
    change_pct = ((close_val - prev_val) / prev_val * 100) if prev_val else 0.0
    if math.isnan(change_pct) or math.isinf(change_pct):
        change_pct = 0.0
    else:
        change_pct = round(change_pct, 2)
        
    uptrend = close_val > sma200_val
    
    # Hitung data seri historis untuk grafik trend IHSG (250 bar terakhir)
    idx_sma200 = idx["Close"].rolling(200).mean()
    sub_idx = idx.tail(250)
    sub_sma = idx_sma200.tail(250)
    
    close_series = []
    sma_series = []
    for d, c, s in zip(sub_idx.index, sub_idx["Close"], sub_sma):
        t_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
        if not math.isnan(c):
            close_series.append({"time": t_str, "value": round(float(c), 2)})
        if s is not None and not math.isnan(s):
            sma_series.append({"time": t_str, "value": round(float(s), 2)})

    # Dapatkan waktu WIB terkini
    try:
        now = datetime.now(ZoneInfo("Asia/Jakarta")) if ZoneInfo else datetime.now()
    except Exception:
        now = datetime.now()
    now_wib = now.strftime("%a %Y-%m-%d %H:%M WIB")

    return {
        "ok": True,
        "index": "IHSG",
        "price": close_val,
        "change_pct": change_pct,
        "sma200": sma200_val,
        "trend": "UPTREND" if uptrend else "DOWNTREND",
        "verdict": ("Pasar uptrend — kondisi mendukung entry"
                    if uptrend else "Pasar downtrend — disiplin & selektif"),
        "now_wib": now_wib,
        "close_series": close_series,
        "sma200_series": sma_series,
    }


@router.get("/sharia/{ticker}")
def sharia(ticker: str):
    """Screening kepatuhan syariah satu saham (Fatwa DSN-MUI)."""
    return sharia_screening.screen_sharia(ticker)


@router.get("/screen")
def screen(
    limit: int | None = Query(None, ge=1, le=100),
    potensi: str | None = Query(None),
    stoch_rsi_range: str | None = Query(None),
    golden_cross: str | None = Query(None),
):
    """Jalankan Stock Funnel ke seluruh universe syariah dan ranking hasilnya."""
    return funnel.screen_universe(
        min_magic=0,
        min_canslim=0,
        require_uptrend=False,
        limit=limit,
        potensi=potensi,
        stoch_rsi_range=stoch_rsi_range,
        golden_cross=golden_cross,
    )


_TV_SELL_LABELS = ("SELL", "STRONG SELL")


def _held_positions() -> dict[str, dict]:
    """Map ticker -> ringkasan posisi portofolio (lots digabung antar broker/tipe)."""
    from app.core import portfolio
    try:
        positions = portfolio.list_positions().get("positions", [])
    except Exception:  # noqa: BLE001
        positions = []
    held: dict[str, dict] = {}
    for p in positions:
        tk = (p.get("ticker") or "").upper().strip()
        if not tk:
            continue
        h = held.setdefault(tk, {"lots": 0, "pl_pct": None, "type": p.get("type", "trading")})
        h["lots"] += int(p.get("lots") or 0)
        if h["pl_pct"] is None:
            h["pl_pct"] = p.get("net_pl_pct", p.get("pl_pct"))
        if p.get("type") == "investasi":
            h["type"] = "investasi"   # tandai bila ada porsi investasi tahunan
    return held


@router.get("/cross-check")
def cross_check(limit: int | None = Query(None, ge=1, le=100)):
    """Radar cross-check TradingView, sadar-portofolio (syariah long-only).

    Dua kelompok terpisah:
      - sell_signals : saham YANG DIMILIKI di portofolio dgn teknikal TradingView
        SELL/STRONG SELL → rekomendasi SELL/exit yang actionable. SELL hanya
        diberikan untuk saham yang benar-benar dipegang (tak bisa jual yang tak
        dimiliki — tunai, long-only).
      - buy_warnings : kandidat BELI (BUKAN milik) yang teknikal TradingView SELL
        → sekadar peringatan "tunda beli", BUKAN rekomendasi SELL.

    Aktif bila settings.data_source memakai TradingView (hybrid/tradingview).
    """
    data = funnel.screen_universe(min_magic=0, min_canslim=0,
                                  require_uptrend=False, limit=limit)
    rows = data.get("hasil", [])
    held = _held_positions()

    items: list[dict] = []
    for r in rows:
        cc = r.get("tv_cross_check")
        if not cc or not cc.get("recommend_label"):
            continue
        items.append({
            "ticker": r["ticker"],
            "name": r.get("name"),
            "sector": r.get("sector"),
            "aksi": r.get("aksi"),
            "final_signal": r.get("final_signal"),
            "css": r.get("css"),
            "fundamental_label": r.get("fundamental_label"),
            "magic_score": r.get("magic_score"),
            "skor": r.get("skor"),
            "price": r.get("price"),
            "tv_recommend": cc.get("recommend_label"),
            "tv_recommend_all": cc.get("recommend_all"),
            "contradiction": bool(cc.get("contradiction")),
        })

    sell_signals: list[dict] = []
    buy_warnings: list[dict] = []
    for it in items:
        pos = held.get(it["ticker"])
        it["in_portfolio"] = bool(pos)
        tv_sell = it["tv_recommend"] in _TV_SELL_LABELS
        if pos and tv_sell:
            # SELL hanya untuk saham yang dimiliki.
            it["action"] = "SELL"
            it["lots"] = pos.get("lots")
            it["pl_pct"] = pos.get("pl_pct")
            it["pos_type"] = pos.get("type")
            sell_signals.append(it)
        elif it["contradiction"] and not pos:
            # Kontradiksi pada saham yang tidak dimiliki -> hanya tunda beli.
            it["action"] = "TUNDA_BELI"
            buy_warnings.append(it)

    sell_signals.sort(key=lambda x: (x.get("tv_recommend_all") if x.get("tv_recommend_all") is not None else 0))
    buy_warnings.sort(key=lambda x: x.get("skor") or 0, reverse=True)

    scanned = {r["ticker"] for r in rows}
    held_uncovered = sorted(tk for tk in held if tk not in scanned)

    return {
        "enabled": len(items) > 0,    # False jika data_source bukan TradingView/hybrid
        "total_lolos": len(rows),
        "with_tv": len(items),
        "portfolio_count": len(held),
        "sell_count": len(sell_signals),
        "warning_count": len(buy_warnings),
        "sell_signals": sell_signals,
        "buy_warnings": buy_warnings,
        "held_uncovered": held_uncovered,   # saham dipegang tapi di luar scan universe
    }
