"""
TradingView data provider — fundamental & rekomendasi teknikal LIVE untuk BEI.

Mengambil data dari scanner publik TradingView (region "indonesia"). Satu request
batch mengembalikan fundamental seluruh universe (ROE/ROA/DER/PBV/PER/EPS growth/
BVPS/Dividend Yield) + Recommend.All — jauh lebih segar & akurat untuk saham IDX
dibanding yfinance, dan tidak membeku seperti master_data CSV.

Schema keluaran `metrics()` SENGAJA disamakan dengan bentuk akhir yang dikonsumsi
`fundamental._metrics()` (der sebagai RASIO, persen sebagai persen) agar bisa
dipasang sebagai sumber alternatif tanpa mengubah logika screening.

Tidak butuh MCP / Claude Desktop berjalan: aplikasi menarik datanya sendiri.
Advisory-only — hanya data analitik, tidak ada eksekusi order.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from app.config import CACHE_DIR, settings

SCANNER_URL = "https://scanner.tradingview.com/{screener}/scan"

# Kolom scanner -> makna (unit dikomentari). Diverifikasi terhadap BBCA/ANTM/ACES.
COLUMNS = [
    "name",                                       # kode emiten
    "close",                                       # harga terakhir (= market price)
    "price_earnings_ttm",                          # PER (x)
    "price_book_fq",                               # PBV (x)
    "return_on_equity",                            # ROE (%)
    "return_on_assets",                            # ROA (%)
    "debt_to_equity",                              # DER (RASIO, mis 0.15 = 15%)
    "earnings_per_share_basic_ttm",                # EPS TTM (level)
    "earnings_per_share_diluted_qoq_growth_fq",    # EPS QnQ growth (%) -> CAN SLIM C
    "earnings_per_share_diluted_yoy_growth_ttm",   # EPS YoY growth (%)
    "book_value_per_share_fq",                     # BVPS (level)
    "total_shares_outstanding_fundamental",        # jumlah saham beredar
    "dividends_yield_current",                     # Dividend Yield kini (%)
    "dividends_yield",                             # Dividend Yield TTM (%) — fallback
    "Recommend.All",                               # rekomendasi teknikal TV (-1..+1)
    "Recommend.MA",                                # komponen Moving Average (-1..+1)
    "Recommend.Other",                             # komponen oscillator (-1..+1)
]
_IDX = {c: i for i, c in enumerate(COLUMNS)}

_CACHE_FILE = CACHE_DIR / "tradingview_scan.json"
_TECH_CACHE_FILE = CACHE_DIR / "tradingview_tech.json"

# Indikator snapshot (1 timeframe) dari tradingview-ta — dipakai sebagai fallback
# teknikal saat OHLCV yfinance gagal. Nilai = persis seperti chart TradingView.
_TECH_FIELDS = [
    "close", "open", "high", "low", "volume", "change",
    "RSI", "Stoch.K", "Stoch.D", "SMA20", "SMA50", "SMA200", "EMA20",
    "MACD.macd", "MACD.signal", "ADX", "ADX+DI", "ADX-DI", "ATR",
]


# --------------------------------------------------------------------------- #
#  Util                                                                       #
# --------------------------------------------------------------------------- #
def _num(v: Any) -> Optional[float]:
    """Angka float aman; None untuk null/NaN/non-numerik."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _pos(v: Optional[float]) -> Optional[float]:
    """Ratio harga (PER/PBV) hanya valid bila > 0; selain itu n/a."""
    return v if (v is not None and v > 0) else None


def recommendation_label(rec_all: Optional[float]) -> str:
    """Petakan Recommend.All (-1..+1) -> label gaya TradingView."""
    if rec_all is None:
        return "NO DATA"
    if rec_all >= 0.5:
        return "STRONG BUY"
    if rec_all >= 0.1:
        return "BUY"
    if rec_all > -0.1:
        return "NEUTRAL"
    if rec_all > -0.5:
        return "SELL"
    return "STRONG SELL"


# --------------------------------------------------------------------------- #
#  Cache disk (per-ticker, TTL)                                               #
# --------------------------------------------------------------------------- #
def _load_cache(path: Path = _CACHE_FILE) -> dict[str, dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict[str, dict[str, Any]], path: Path = _CACHE_FILE) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _fresh(entry: dict[str, Any], ttl: int) -> bool:
    return (time.time() - entry.get("ts", 0)) < ttl


# --------------------------------------------------------------------------- #
#  Pengambilan batch                                                          #
# --------------------------------------------------------------------------- #
def _to_metrics(row_d: list[Any]) -> dict[str, Any]:
    """Satu baris scanner -> schema yang dikonsumsi fundamental._metrics()."""
    g = lambda c: _num(row_d[_IDX[c]]) if _IDX[c] < len(row_d) else None  # noqa: E731
    dy = g("dividends_yield_current")
    if dy is None or dy == 0:
        dy = g("dividends_yield")
    return {
        "eps_growth": g("earnings_per_share_diluted_qoq_growth_fq"),
        "eps_yoy": g("earnings_per_share_diluted_yoy_growth_ttm"),
        "roa": g("return_on_assets"),
        "roe": g("return_on_equity"),
        "der": g("debt_to_equity"),                 # sudah rasio
        "pbv": _pos(g("price_book_fq")),
        "per": _pos(g("price_earnings_ttm")),
        "dy": dy,
        "bvps": g("book_value_per_share_fq"),
        "mp": g("close"),
        "eps_ttm": g("earnings_per_share_basic_ttm"),
        "shares": g("total_shares_outstanding_fundamental"),
        "recommend_all": g("Recommend.All"),
        "recommend_ma": g("Recommend.MA"),
        "recommend_other": g("Recommend.Other"),
        "recommend_label": recommendation_label(g("Recommend.All")),
        "source": "tradingview",
    }


def _fetch_batch(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Ambil fundamental sekumpulan ticker dalam SATU request scanner."""
    if not tickers:
        return {}
    import httpx

    exch = settings.tradingview_exchange
    payload = {
        "symbols": {"tickers": [f"{exch}:{t}" for t in tickers], "query": {"types": []}},
        "columns": COLUMNS,
    }
    url = SCANNER_URL.format(screener=settings.tradingview_screener)
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    with httpx.Client(timeout=25.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json().get("data", []) or []

    out: dict[str, dict[str, Any]] = {}
    for row in data:
        sym = (row.get("s") or "").split(":")[-1].upper()
        if sym:
            out[sym] = _to_metrics(row.get("d") or [])
    return out


# --------------------------------------------------------------------------- #
#  API publik                                                                 #
# --------------------------------------------------------------------------- #
def scan_fundamentals(tickers: list[str], *, force: bool = False) -> dict[str, dict[str, Any]]:
    """Fundamental TradingView untuk daftar ticker (pakai cache TTL per-ticker)."""
    tickers = [t.strip().upper() for t in tickers if t and t.strip()]
    ttl = settings.tradingview_ttl_seconds
    cache = {} if force else _load_cache()

    result: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for t in tickers:
        entry = cache.get(t)
        if entry and _fresh(entry, ttl) and entry.get("data"):
            result[t] = entry["data"]
        else:
            missing.append(t)

    if missing:
        fetched = _fetch_batch(missing)
        now = time.time()
        for t, m in fetched.items():
            result[t] = m
            cache[t] = {"ts": now, "data": m}
        _save_cache(cache)

    return result


def metrics(ticker: str, *, force: bool = False) -> Optional[dict[str, Any]]:
    """Fundamental TradingView untuk 1 saham, atau None bila gagal/kosong."""
    data = scan_fundamentals([ticker], force=force)
    return data.get(ticker.strip().upper())


def available() -> bool:
    """True bila TradingView dapat dihubungi (cek ringan 1 ticker)."""
    try:
        return metrics("BBCA") is not None
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Snapshot teknikal (tradingview-ta) — fallback saat OHLCV yfinance gagal     #
# --------------------------------------------------------------------------- #
def technical_snapshot(ticker: str, *, interval: str = "1d",
                       force: bool = False) -> Optional[dict[str, Any]]:
    """Indikator teknikal terkini 1 saham dari TradingView (RSI/Stoch/SMA/MACD/ADX
    + rekomendasi MA/Oscillator/Summary). None bila lib/jaringan gagal. Cache TTL."""
    tk = ticker.strip().upper()
    ttl = settings.tradingview_ttl_seconds
    cache = {} if force else _load_cache(_TECH_CACHE_FILE)
    entry = cache.get(tk)
    if entry and _fresh(entry, ttl) and entry.get("data"):
        return entry["data"]

    try:
        from tradingview_ta import TA_Handler, Interval
    except Exception:
        return None

    imap = {
        "1d": Interval.INTERVAL_1_DAY, "1w": Interval.INTERVAL_1_WEEK,
        "1m": Interval.INTERVAL_1_MONTH, "4h": Interval.INTERVAL_4_HOURS,
        "1h": Interval.INTERVAL_1_HOUR,
    }
    try:
        handler = TA_Handler(
            symbol=tk, screener=settings.tradingview_screener,
            exchange=settings.tradingview_exchange,
            interval=imap.get(interval, Interval.INTERVAL_1_DAY),
        )
        a = handler.get_analysis()
    except Exception:  # noqa: BLE001 — jaringan/symbol tak dikenal
        return None

    ind = a.indicators or {}
    snap: dict[str, Any] = {f: _num(ind.get(f)) for f in _TECH_FIELDS}
    snap["rec_ma"] = (a.moving_averages or {}).get("RECOMMENDATION")
    snap["rec_osc"] = (a.oscillators or {}).get("RECOMMENDATION")
    snap["rec_summary"] = (a.summary or {}).get("RECOMMENDATION")
    snap["source"] = "tradingview_ta"

    cache[tk] = {"ts": time.time(), "data": snap}
    _save_cache(cache, _TECH_CACHE_FILE)
    return snap
