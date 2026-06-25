"""
Data provider — mengambil data harga & fundamental saham BEI via yfinance.

Saham BEI memakai suffix ".JK" di Yahoo Finance (mis. BBCA -> BBCA.JK).
Hasil di-cache ke disk (TTL configurable) agar tidak memukul API berulang.
"""

from __future__ import annotations

import csv
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from app.config import CACHE_DIR, DATA_DIR, settings

CACHE_DIR.mkdir(parents=True, exist_ok=True)

INDEX_TICKER = "^JKSE"  # IHSG (Jakarta Composite Index)


_SESSION = None


def _session():
    """Sesi curl_cffi (impersonate browser) untuk menghindari rate-limit Yahoo."""
    global _SESSION
    if _SESSION is None:
        try:
            from curl_cffi import requests as cffi_requests
            _SESSION = cffi_requests.Session(impersonate="chrome")
        except Exception:
            _SESSION = False  # tidak tersedia -> pakai default yfinance
    return _SESSION or None


def _ticker(symbol: str):
    yf = _yf()
    sess = _session()
    try:
        return yf.Ticker(symbol, session=sess) if sess else yf.Ticker(symbol)
    except TypeError:
        return yf.Ticker(symbol)


def _yf():
    """Import yfinance lazily supaya unit-test math tidak butuh jaringan."""
    import yfinance as yf
    return yf


def to_yahoo(ticker: str) -> str:
    ticker = ticker.strip().upper()
    # index (^JKSE), futures (GC=F), forex (IDR=X), crypto (BTC-USD) -> tanpa .JK
    if ticker.startswith("^") or "=" in ticker or "-" in ticker:
        return ticker
    return ticker if ticker.endswith(".JK") else f"{ticker}.JK"


# --------------------------------------------------------------------------- #
#  Universe                                                                   #
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def get_universe() -> list[dict[str, str]]:
    """Daftar saham syariah. Utama: master_data_syariah.csv (75 DES terkurasi)."""
    from app.data import master_data
    if master_data.available():
        return master_data.universe()
    path = DATA_DIR / "sharia_universe.csv"
    with open(path, newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def universe_tickers() -> list[str]:
    return [row["ticker"] for row in get_universe()]


def sector_of(ticker: str) -> Optional[str]:
    for row in get_universe():
        if row["ticker"] == ticker.upper():
            return row["sector"]
    return None


# --------------------------------------------------------------------------- #
#  Cache helpers                                                              #
# --------------------------------------------------------------------------- #
def _fresh(path: Path, ttl: Optional[int] = None) -> bool:
    ttl = settings.cache_ttl_seconds if ttl is None else ttl
    return path.exists() and (time.time() - path.stat().st_mtime) < ttl


# --------------------------------------------------------------------------- #
#  History (OHLCV)                                                            #
# --------------------------------------------------------------------------- #
def get_history(ticker: str, period: str = "2y", interval: str = "1d",
                ttl: Optional[int] = None) -> pd.DataFrame:
    """`ttl` = umur cache khusus (detik); None = pakai settings.cache_ttl_seconds.
    Berguna utk harga posisi/jual yang ingin lebih live (intraday)."""
    if ttl is None:
        # Cache 4 jam untuk data indeks/komoditas/forex harian karena lambat & jarang berubah
        is_non_stock = ticker.startswith("^") or "=" in ticker or "-" in ticker
        if is_non_stock and interval == "1d":
            ttl = 14400
        else:
            ttl = settings.cache_ttl_seconds

    cache = CACHE_DIR / f"{to_yahoo(ticker).replace('^', '_idx_')}_{period}_{interval}.csv"
    if _fresh(cache, ttl):
        try:
            df = pd.read_csv(cache, index_col=0, parse_dates=True)
            if not df.empty:
                return df
        except Exception:
            pass

    try:
        yf_ticker = _ticker(to_yahoo(ticker))
        df = yf_ticker.history(period=period, interval=interval, auto_adjust=False)
    except Exception:
        df = None
        yf_ticker = None
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")

    # Mengatasi nilai Close NaN pada bar harian terbaru (misal akibat data intraday belum final)
    if not df.empty and pd.isna(df["Close"].iloc[-1]) and yf_ticker is not None:
        try:
            last_price = yf_ticker.fast_info["lastPrice"]
            if last_price is not None and not pd.isna(last_price) and last_price > 0:
                df.iloc[-1, df.columns.get_loc("Close")] = last_price
        except Exception:
            pass

    try:
        df.to_csv(cache)   # cache hanya bila ada data
    except Exception:
        pass
    return df


# --------------------------------------------------------------------------- #
#  Fundamental info                                                           #
# --------------------------------------------------------------------------- #
def get_info(ticker: str) -> dict[str, Any]:
    cache = CACHE_DIR / f"{to_yahoo(ticker)}_info.json"
    # Info fundamental perusahaan cukup di-cache selama 7 hari
    if _fresh(cache, ttl=86400 * 7):
        try:
            return json.loads(cache.read_text())
        except Exception:
            pass

    try:
        info = dict(_ticker(to_yahoo(ticker)).info)
    except Exception:
        info = {}
    # buang yang tidak JSON-serializable
    clean = {k: v for k, v in info.items() if isinstance(v, (str, int, float, bool, type(None)))}
    # cache hanya bila info bermakna (hindari menyimpan {} akibat rate-limit)
    if len(clean) > 5:
        try:
            cache.write_text(json.dumps(clean))
        except Exception:
            pass
    return clean


def _eps_from_statement(stmt: pd.DataFrame) -> Optional[pd.Series]:
    """Ambil baris EPS dari income statement yfinance (kolom = periode)."""
    if stmt is None or stmt.empty:
        return None
    for key in ("Diluted EPS", "Basic EPS"):
        if key in stmt.index:
            s = stmt.loc[key].dropna()
            if not s.empty:
                # kolom = Timestamp periode; urutkan lama -> baru
                return s.sort_index()
    return None


def get_quarterly_eps(ticker: str) -> Optional[pd.Series]:
    cache = CACHE_DIR / f"{to_yahoo(ticker)}_q_eps.json"
    # EPS kuartalan cukup di-cache selama 7 hari
    if _fresh(cache, ttl=86400 * 7):
        try:
            d = json.loads(cache.read_text())
            # Pastikan format index parsed as datetime
            return pd.Series(d, dtype=float).sort_index()
        except Exception:
            pass

    try:
        s = _eps_from_statement(_ticker(to_yahoo(ticker)).quarterly_income_stmt)
        if s is not None and not s.empty:
            d = {str(k)[:10]: float(v) for k, v in s.items()}
            cache.write_text(json.dumps(d))
            return s
    except Exception:
        pass
    return None


def get_annual_eps(ticker: str) -> Optional[pd.Series]:
    cache = CACHE_DIR / f"{to_yahoo(ticker)}_a_eps.json"
    # EPS tahunan cukup di-cache selama 7 hari
    if _fresh(cache, ttl=86400 * 7):
        try:
            d = json.loads(cache.read_text())
            # Pastikan format index parsed as datetime
            return pd.Series(d, dtype=float).sort_index()
        except Exception:
            pass

    try:
        s = _eps_from_statement(_ticker(to_yahoo(ticker)).income_stmt)
        if s is not None and not s.empty:
            d = {str(k)[:10]: float(v) for k, v in s.items()}
            cache.write_text(json.dumps(d))
            return s
    except Exception:
        pass
    return None


def get_index_history(period: str = "2y") -> pd.DataFrame:
    # Menggunakan TTL 4 jam (14400 detik) untuk IHSG
    return get_history(INDEX_TICKER, period=period, ttl=14400)
