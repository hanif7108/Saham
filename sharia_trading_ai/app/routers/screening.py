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


_BUY_ISH = ("STRONG BUY", "BUY", "SPECULATIVE BUY", "ACCUMULATE")


def _accuracy_map(tickers: list[str]) -> dict[str, dict]:
    """Win-rate backtest (akurasi prediksi) untuk daftar ticker — paralel.

    Sumber metrik SAMA dengan Pusat Keputusan (undervalue.evaluate -> backtest).
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.core import undervalue

    def _one(tk: str):
        try:
            uv = undervalue.evaluate(tk)
            bt = (uv.get("backtest") or {}) if uv else {}
            return tk, {"akurasi_pct": bt.get("win_rate"), "akurasi_n": bt.get("n_signals")}
        except Exception:  # noqa: BLE001
            return tk, {"akurasi_pct": None, "akurasi_n": None}

    if not tickers:
        return {}
    with ThreadPoolExecutor(max_workers=min(6, len(tickers))) as ex:
        return {tk: acc for tk, acc in ex.map(_one, tickers)}


@router.get("/cross-check")
def cross_check(top: int = Query(5, ge=1, le=15),
                min_acc: float = Query(50.0, ge=0, le=100)):
    """Radar cross-check TradingView — fokus & efisien sesuai money management.

    BELI: hanya `top` (default 5, sesuai batas maks 5 saham/hari) kandidat dengan
    AKURASI PREDIKSI TERTINGGI (win-rate backtest historis) yang LULUS ambang
    `min_acc` (default 50%). Tiap kandidat diberi status SELARAS (teknikal TV
    mendukung) atau TUNDA_BELI (teknikal TV SELL); yang SELARAS disertai saran
    alokasi Money Management (lot/Rp dari cash RDN). Efisien: backtest hanya pada
    shortlist skor-teratas, paralel.

    SELL: hanya saham YANG DIMILIKI di portofolio dgn teknikal TV SELL/STRONG SELL
    (syariah long-only — tak bisa jual yang tak dipegang). Tak dibatasi `top`.

    Aktif bila settings.data_source memakai TradingView (hybrid/tradingview).
    """
    from app.core import portfolio, accounts, decisions

    data = funnel.screen_universe(min_magic=0, min_canslim=0, require_uptrend=False)
    rows = data.get("hasil", [])
    held = _held_positions()
    try:
        positions = portfolio.list_positions().get("positions", [])
    except Exception:  # noqa: BLE001
        positions = []
    pos_by_tk = {(p.get("ticker") or "").upper(): p for p in positions}

    items: list[dict] = []
    for r in rows:
        cc = r.get("tv_cross_check")
        if not cc or not cc.get("recommend_label"):
            continue
        items.append({
            "ticker": r["ticker"], "name": r.get("name"), "sector": r.get("sector"),
            "aksi": r.get("aksi"), "final_signal": r.get("final_signal"), "css": r.get("css"),
            "fundamental_label": r.get("fundamental_label"), "magic_score": r.get("magic_score"),
            "skor": r.get("skor"), "price": r.get("price"),
            "tv_recommend": cc.get("recommend_label"), "tv_recommend_all": cc.get("recommend_all"),
            "contradiction": bool(cc.get("contradiction")),
        })

    # ---- SELL: saham dimiliki + teknikal TV SELL (tak dibatasi top) ---- #
    sell_signals: list[dict] = []
    for it in items:
        pos = held.get(it["ticker"])
        it["in_portfolio"] = bool(pos)
        if pos and it["tv_recommend"] in _TV_SELL_LABELS:
            it["action"] = "SELL"
            it["lots"] = pos.get("lots")
            it["pl_pct"] = pos.get("pl_pct")
            it["pos_type"] = pos.get("type")
            sell_signals.append(it)
    sell_signals.sort(key=lambda x: (x.get("tv_recommend_all") if x.get("tv_recommend_all") is not None else 0))

    # ---- BELI: top-N akurasi tertinggi (shortlist by skor -> backtest -> sort) ---- #
    pool = [it for it in items
            if it["final_signal"] in _BUY_ISH
            and it["fundamental_label"] != "AVOID"
            and (it.get("price") or 0) > 0
            and it["ticker"] not in held]          # fokus entri baru; held -> bagian SELL
    pool.sort(key=lambda x: x.get("skor") or 0, reverse=True)
    shortlist = pool[: max(top * 3, 15)]           # lebih luas agar filter ambang punya pilihan
    acc = _accuracy_map([it["ticker"] for it in shortlist])
    for it in shortlist:
        a = acc.get(it["ticker"], {})
        it["akurasi_pct"] = a.get("akurasi_pct")
        it["akurasi_n"] = a.get("akurasi_n")

    # Ambang akurasi minimum: hanya kandidat ber-akurasi >= min_acc (None = tak lolos).
    qualified = [it for it in shortlist
                 if it.get("akurasi_pct") is not None and it["akurasi_pct"] >= min_acc]
    hidden_by_threshold = len(shortlist) - len(qualified)

    # urut: akurasi tertinggi dulu, tie-break skor funnel
    qualified.sort(key=lambda x: (x["akurasi_pct"], x.get("skor") or 0), reverse=True)
    candidates = qualified[:top]

    # Alokasi Money Management hanya untuk kandidat SELARAS (layak beli sekarang).
    # Saring ke RDN yang punya 'advice' (kecualikan akun emas Tring Pegadaian yg
    # advice=None — bila tidak, _alloc_buy crash saat membaca advice.open_slots).
    try:
        rdn_list = [r for r in accounts.breakdown().get("rdn", []) if r.get("advice")]
    except Exception:  # noqa: BLE001
        rdn_list = []
    for it in candidates:
        it["status"] = "TUNDA_BELI" if it["tv_recommend"] in _TV_SELL_LABELS else "SELARAS"
        if it["status"] == "SELARAS":
            try:
                it["alokasi"] = decisions._alloc_buy(it["ticker"], it.get("price"), pos_by_tk, rdn_list)
            except Exception:  # noqa: BLE001
                it["alokasi"] = None

    scanned = {r["ticker"] for r in rows}
    held_uncovered = sorted(tk for tk in held if tk not in scanned)

    return {
        "enabled": len(items) > 0,    # False jika data_source bukan TradingView/hybrid
        "top_n": top,
        "min_acc": min_acc,
        "total_lolos": len(rows),
        "candidate_count": len(candidates),
        "hidden_by_threshold": hidden_by_threshold,
        "tunda_beli_count": sum(1 for c in candidates if c["status"] == "TUNDA_BELI"),
        "selaras_count": sum(1 for c in candidates if c["status"] == "SELARAS"),
        "candidates": candidates,
        "portfolio_count": len(held),
        "sell_count": len(sell_signals),
        "sell_signals": sell_signals,
        "held_uncovered": held_uncovered,
    }
