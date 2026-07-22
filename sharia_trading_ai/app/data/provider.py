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


@lru_cache(maxsize=1)
def us_tickers() -> set[str]:
    path = DATA_DIR / "us_sharia_universe.csv"
    if path.exists():
        try:
            with open(path, newline="", encoding="utf-8") as f:
                return {row["ticker"].upper().strip() for row in csv.DictReader(f) if row.get("ticker")}
        except Exception:
            pass
    return {
        "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "GOOG", "META", "CRM", "ADBE",
        "AMD", "CSCO", "PEP", "AVGO", "QCOM", "INTC", "TXN", "AMAT", "LRCX", "MU",
        "ADI", "CVX", "XOM", "JNJ", "PFE", "MRK"
    }


def is_us_ticker(ticker: str) -> bool:
    ticker = ticker.strip().upper()
    if ticker.endswith(".JK"):
        return False
    if ticker.endswith(".US"):
        return True
    if ticker in us_tickers():
        return True
    return False


def get_us_universe() -> list[dict[str, str]]:
    path = DATA_DIR / "us_sharia_universe.csv"
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            return [
                {
                    "ticker": row["ticker"].upper().strip() + ".US",
                    "name": row.get("name", "").strip(),
                    "sector": row.get("sector", "").strip()
                }
                for row in csv.DictReader(f) if row.get("ticker")
            ]
    fallback_tickers = us_tickers()
    return [
        {
            "ticker": t + ".US",
            "name": t + " Corp",
            "sector": "Technology"
        }
        for t in fallback_tickers
    ]


def us_universe_tickers() -> list[str]:
    return [row["ticker"] for row in get_us_universe()]


def to_yahoo(ticker: str) -> str:
    ticker = ticker.strip().upper()
    # index (^JKSE), futures (GC=F), forex (IDR=X), crypto (BTC-USD) -> tanpa .JK
    if ticker.startswith("^") or "=" in ticker or "-" in ticker:
        return ticker
    if ticker.endswith(".JK"):
        return ticker
    if ticker.endswith(".US"):
        return ticker[:-3]  # strip .US for yfinance
    if is_us_ticker(ticker):
        return ticker
    return f"{ticker}.JK"


# --------------------------------------------------------------------------- #
#  Universe                                                                   #
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def get_universe() -> list[dict[str, str]]:
    """Daftar saham syariah. Utama: master_data_syariah.csv (75 DES terkurasi) + US universe."""
    from app.data import master_data
    idx_list = []
    if master_data.available():
        idx_list = master_data.universe()
    else:
        path = DATA_DIR / "sharia_universe.csv"
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                idx_list = [dict(row) for row in csv.DictReader(f)]
    
    us_list = get_us_universe()
    return idx_list + us_list


def universe_tickers() -> list[str]:
    return [row["ticker"] for row in get_universe()]


def sector_of(ticker: str) -> Optional[str]:
    ticker = ticker.upper().strip()
    for row in get_universe():
        if row["ticker"] == ticker:
            return row["sector"]
    return None


# --------------------------------------------------------------------------- #
#  Cache helpers                                                              #
# --------------------------------------------------------------------------- #
def _fresh(path: Path, ttl: Optional[int] = None) -> bool:
    ttl = settings.cache_ttl_seconds if ttl is None else ttl
    return path.exists() and (time.time() - path.stat().st_mtime) < ttl


# --------------------------------------------------------------------------- #
#  Fallback OHLCV via TradingView (tvdatafeed) — saat yfinance kosong          #
# --------------------------------------------------------------------------- #
_TV_CLIENT = None
_TV_CLIENT_FAILED = False


def _tv_client():
    """Singleton TvDatafeed (guest mode). False bila lib tak ada / gagal init."""
    global _TV_CLIENT, _TV_CLIENT_FAILED
    if _TV_CLIENT_FAILED:
        return None
    if _TV_CLIENT is None:
        try:
            import logging as _lg
            _lg.getLogger("tvDatafeed").setLevel(_lg.CRITICAL)
            from tvDatafeed import TvDatafeed
            _TV_CLIENT = TvDatafeed()  # guest (tanpa login)
        except Exception:
            _TV_CLIENT_FAILED = True
            return None
    return _TV_CLIENT


def _tv_symbol_exchange(ticker: str) -> tuple[Optional[str], Optional[str]]:
    """Petakan ticker app -> (symbol, exchange) TradingView. (None,None) = lewati."""
    t = ticker.strip().upper()
    if t in ("^JKSE", "_IDX_JKSE"):
        return "COMPOSITE", "IDX"        # IHSG
    if t.startswith("^") or "=" in t or "-" in t:
        return None, None                # komoditas/forex/indeks lain: lewati
    return t.replace(".JK", ""), "IDX"   # saham BEI


def _tv_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """OHLCV dari TradingView (tvdatafeed), format selaras yfinance. Empty bila gagal.

    Dipakai sebagai fallback HISTORY penuh saat yfinance kosong, supaya seluruh
    mesin teknikal (S/R, Fibonacci, candle) tetap jalan. Aktif hanya pada
    settings.data_source = tradingview/hybrid. Retry utk atasi flakiness guest mode.
    """
    if (settings.data_source or "").lower() not in ("tradingview", "hybrid"):
        return pd.DataFrame()
    if interval not in ("1d", "1wk", "1mo"):   # fallback fokus pada timeframe harian/dst
        return pd.DataFrame()
    sym, exch = _tv_symbol_exchange(ticker)
    if sym is None:
        return pd.DataFrame()
    client = _tv_client()
    if client is None:
        return pd.DataFrame()

    try:
        from tvDatafeed import Interval as _TvInt
    except Exception:
        return pd.DataFrame()
    imap = {"1d": _TvInt.in_daily, "1wk": _TvInt.in_weekly, "1mo": _TvInt.in_monthly}
    nbars = {"1mo": 30, "3mo": 80, "6mo": 150, "1y": 280, "2y": 560, "5y": 1300}.get(period, 560)

    df = None
    for _ in range(3):  # guest mode kadang balas None pada panggilan beruntun
        try:
            df = client.get_hist(symbol=sym, exchange=exch,
                                 interval=imap[interval], n_bars=nbars)
        except Exception:
            df = None
        if df is not None and not df.empty:
            break
        time.sleep(1.0)
    if df is None or df.empty:
        return pd.DataFrame()

    # Selaraskan dengan format yfinance: kolom Title-case, drop 'symbol'.
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df = df[cols].dropna(how="all")
    df.index.name = None
    return df


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
        # yfinance kosong -> coba OHLCV penuh dari TradingView (tvdatafeed).
        tv_df = _tv_history(ticker, period, interval)
        if not tv_df.empty:
            try:
                tv_df.to_csv(cache)   # cache seperti jalur yfinance
            except Exception:
                pass
            return tv_df
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
            res = json.loads(cache.read_text())
            if isinstance(res, dict) and res.get("error") == "empty":
                return {}
            return res
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
    else:
        try:
            # Cache sentinel kosong untuk mencegah cache stampede selama 1 hari
            cache.write_text(json.dumps({"error": "empty"}))
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
            if isinstance(d, dict) and d.get("error") == "empty":
                return None
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
        else:
            cache.write_text(json.dumps({"error": "empty"}))
    except Exception:
        try:
            cache.write_text(json.dumps({"error": "empty"}))
        except Exception:
            pass
    return None


def get_annual_eps(ticker: str) -> Optional[pd.Series]:
    cache = CACHE_DIR / f"{to_yahoo(ticker)}_a_eps.json"
    # EPS tahunan cukup di-cache selama 7 hari
    if _fresh(cache, ttl=86400 * 7):
        try:
            d = json.loads(cache.read_text())
            if isinstance(d, dict) and d.get("error") == "empty":
                return None
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
        else:
            cache.write_text(json.dumps({"error": "empty"}))
    except Exception:
        try:
            cache.write_text(json.dumps({"error": "empty"}))
        except Exception:
            pass
    return None


@lru_cache(maxsize=128)
def get_usd_idr_rate(ttl_seconds: int = 14400) -> float:
    try:
        # Fetch USD/IDR exchange rate
        df = get_history("IDR=X", period="5d", ttl=ttl_seconds)
        if df is not None and not df.empty:
            val = float(df["Close"].iloc[-1])
            if val > 0:
                return round(val, 2)
    except Exception:
        pass
    return 16000.0  # fallback


def get_index_ticker_for(ticker: Optional[str]) -> str:
    if ticker and is_us_ticker(ticker):
        return "^GSPC"  # S&P 500
    return INDEX_TICKER  # IHSG (^JKSE)


def get_index_history(ticker: Optional[str] = None, period: str = "2y") -> pd.DataFrame:
    idx_ticker = get_index_ticker_for(ticker)
    # Menggunakan TTL 4 jam (14400 detik) untuk indeks pasar
    return get_history(idx_ticker, period=period, ttl=14400)
