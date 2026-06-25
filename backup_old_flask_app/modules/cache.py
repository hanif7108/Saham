"""
Cache Layer
===========
Caching ringan berbasis filesystem untuk:
  - Harga historis (yfinance) → simpan parquet/csv per ticker
  - Info fundamental (yfinance + scraper) → simpan JSON per ticker

Tujuan: hindari rate-limit Yahoo Finance dan scraping berulang.

Fitur (post-patch PERBAIKAN_SAHAM.md):
  • TTL adaptif: di luar jam pasar TTL diperpanjang minimal 6 jam — hindari
    fetch ulang yang sia-sia karena harga tidak berubah.
  • Stale-cache fallback: jika fetch gagal (rate-limit yfinance, network down),
    pakai data cache lama meskipun sudah expired.
  • Logging terstruktur via modul `logging` (bukan print) — log keluar ke
    stderr → ke gunicorn_error.log → ke launchd_stderr.log.

API:
    cache = Cache("/Users/hanif/Saham/cache")
    df = cache.get_history("BRIS", period="3mo", ttl_minutes=60)
    info = cache.get_info("BRIS", ttl_minutes=720)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional, Set

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

# Awareness sesi IDX. Import dari modul terpisah agar logikanya konsisten
# di seluruh aplikasi (scheduler, app endpoints, cache).
try:
    from modules.market_hours import is_market_open
except Exception:  # pragma: no cover — defensive
    def is_market_open() -> bool:  # type: ignore
        return False


logger = logging.getLogger(__name__)

# Saat pasar tutup: TTL minimum 6 jam untuk hindari fetch berulang.
CLOSED_MARKET_MIN_TTL_MIN = 6 * 60


def _effective_ttl(ttl_minutes: int) -> int:
    """
    Perpanjang TTL otomatis saat pasar IDX tutup.
    Saat market open → pakai TTL asli (mis. 5 menit untuk scalping).
    Saat market closed → minimum 6 jam.
    """
    if is_market_open():
        return ttl_minutes
    return max(ttl_minutes, CLOSED_MARKET_MIN_TTL_MIN)


# Backward-compat: beberapa modul lama mungkin import is_idx_market_open dari sini.
def is_idx_market_open() -> bool:
    return is_market_open()


# ----------------------------- MULTI-MARKET ROUTING ----------------------------- #
# Cache perlu tahu ticker mana yang IDX (auto-append .JK) vs US (apa adanya).
# Kita load universe US sekali (cached), lalu cek membership saat _yf_ticker().

_US_UNIVERSE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "daftar_saham_syariah_us.csv",
)
_US_UNIVERSE_CACHE: Set[str] = set()
_US_UNIVERSE_LOADED = False


def _load_us_universe() -> Set[str]:
    """Lazy-load daftar ticker US Sharia. Returns set ticker uppercase."""
    global _US_UNIVERSE_CACHE, _US_UNIVERSE_LOADED
    if _US_UNIVERSE_LOADED:
        return _US_UNIVERSE_CACHE
    try:
        if os.path.exists(_US_UNIVERSE_PATH):
            df = pd.read_csv(_US_UNIVERSE_PATH)
            _US_UNIVERSE_CACHE = {str(t).upper().strip() for t in df["Ticker"].dropna()}
            logger.info("Loaded US Sharia universe: %d tickers", len(_US_UNIVERSE_CACHE))
    except Exception as e:
        logger.warning("Failed to load US universe: %s", e)
        _US_UNIVERSE_CACHE = set()
    _US_UNIVERSE_LOADED = True
    return _US_UNIVERSE_CACHE


def _resolve_yf_ticker(ticker: str, market: Optional[str] = None) -> str:
    """
    Resolve simbol yfinance untuk ticker dari universe IDX vs US.

    Aturan:
      - market="US"        → pakai apa adanya (AAPL, NVDA)
      - market="ID"        → suffix .JK (BRIS → BRIS.JK)
      - market=None (auto) →
          * starts with ^ (index)        → as-is (^JKSE, ^GSPC, ^IXIC)
          * mengandung "." atau "="      → as-is (BRK.B, GC=F, USDIDR=X)
          * ada di US universe           → as-is
          * default                      → suffix .JK (asumsi IDX)
    """
    t = str(ticker).upper().strip()
    if market == "US":
        return t
    if market == "ID":
        return t if t.endswith(".JK") else f"{t}.JK"
    # AUTO
    if t.startswith("^") or "=" in t:
        return t
    if "." in t:
        # Sudah pakai suffix (mis. BRK.B, BRIS.JK) — pakai apa adanya
        return t
    if t in _load_us_universe():
        return t
    return f"{t}.JK"


class Cache:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self.history_dir = os.path.join(cache_dir, "history")
        self.info_dir = os.path.join(cache_dir, "info")
        os.makedirs(self.history_dir, exist_ok=True)
        os.makedirs(self.info_dir, exist_ok=True)

    # ---------- HISTORY (OHLC) ----------

    def _hist_path(self, ticker: str, period: str, market: Optional[str] = None) -> str:
        safe_ticker = ticker.upper().replace(".", "_")
        # Untuk US, prefix file dengan "US_" supaya tidak collide dengan ticker IDX
        # yang kebetulan punya nama sama (jarang, tapi defensive).
        if market == "US" or ticker.upper() in _load_us_universe():
            safe_ticker = f"US_{safe_ticker}"
        return os.path.join(self.history_dir, f"{safe_ticker}_{period}.csv")

    def _read_cached_history(self, path: str) -> Optional[pd.DataFrame]:
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if "Close" in df.columns:
                df = df.dropna(subset=["Close"])  # buang bar kosong (lihat get_history)
            if not df.empty:
                return df
        except Exception as e:
            logger.warning("read cached history failed for %s: %s", path, e)
        return None

    def get_history(
        self,
        ticker: str,
        period: str = "3mo",
        ttl_minutes: int = 60,
        force_refresh: bool = False,
        market: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Ambil harga historis dengan cache TTL menit (adaptif jam pasar).

        Args:
            market: "ID" | "US" | None. Kalau None, auto-detect dari universe.
        """
        path = self._hist_path(ticker, period, market=market)
        effective_ttl = _effective_ttl(ttl_minutes)

        # 1) Try fresh cache
        if not force_refresh and os.path.exists(path):
            age_min = (time.time() - os.path.getmtime(path)) / 60
            if age_min < effective_ttl:
                cached = self._read_cached_history(path)
                if cached is not None:
                    return cached

        # 2) Fetch fresh
        if yf is None:
            logger.warning("yfinance not installed; cannot fetch %s", ticker)
            return self._read_cached_history(path) if os.path.exists(path) else None

        try:
            yf_ticker = _resolve_yf_ticker(ticker, market=market)
            stock = yf.Ticker(yf_ticker)
            # auto_adjust=False → pakai harga ASLI (raw OHLC) agar cocok dengan
            # TradingView & aplikasi broker. Tanpa flag ini, yfinance>=0.2 default
            # auto_adjust=True yang menggeser harga historis karena dividen, sehingga
            # MA/level/sinyal jadi melenceng & tidak match harga yang dilihat user.
            df = stock.history(period=period, auto_adjust=False)
            if df is not None and not df.empty:
                # Buang baris bar "kosong": yfinance kadang mengembalikan baris
                # trailing untuk hari berjalan dgn OHLC=NaN (pasar belum ada
                # transaksi tercatat). Jika dibiarkan, close.iloc[-1] jadi NaN dan
                # merusak seluruh perhitungan sinyal teknikal.
                df = df.dropna(subset=["Close"])
            if df is not None and not df.empty:
                df.to_csv(path)
                return df
            logger.warning("history empty for %s (yf=%s, %s)", ticker, yf_ticker, period)
        except Exception as e:
            logger.warning("history fetch error %s: %s", ticker, e)

        # 3) Stale-cache fallback
        if os.path.exists(path):
            logger.info("using stale cache for history %s", ticker)
            return self._read_cached_history(path)
        return None

    # ---------- INFO (Fundamental yfinance dict) ----------

    def _info_path(self, ticker: str, market: Optional[str] = None) -> str:
        safe_ticker = ticker.upper().replace(".", "_")
        if market == "US" or ticker.upper() in _load_us_universe():
            safe_ticker = f"US_{safe_ticker}"
        return os.path.join(self.info_dir, f"{safe_ticker}.json")

    def _read_cached_info(self, path: str) -> Optional[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("read cached info failed for %s: %s", path, e)
        return None

    def get_info(
        self,
        ticker: str,
        ttl_minutes: int = 12 * 60,  # default 12 jam
        force_refresh: bool = False,
        market: Optional[str] = None,
    ) -> Optional[dict]:
        """Ambil info fundamental yfinance dengan cache (adaptif jam pasar).

        Args:
            market: "ID" | "US" | None. None → auto-detect dari universe.
        """
        path = self._info_path(ticker, market=market)
        effective_ttl = _effective_ttl(ttl_minutes)

        if not force_refresh and os.path.exists(path):
            age_min = (time.time() - os.path.getmtime(path)) / 60
            if age_min < effective_ttl:
                cached = self._read_cached_info(path)
                if cached is not None:
                    return cached

        if yf is None:
            return self._read_cached_info(path) if os.path.exists(path) else None

        try:
            yf_ticker = _resolve_yf_ticker(ticker, market=market)
            stock = yf.Ticker(yf_ticker)
            info = stock.info or {}
            # Filter hanya nilai serializable
            clean = {
                k: v
                for k, v in info.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(clean, f, indent=2)
            return clean
        except Exception as e:
            logger.warning("info fetch error %s: %s", ticker, e)

        # Stale-cache fallback
        if os.path.exists(path):
            logger.info("using stale cache for info %s", ticker)
            return self._read_cached_info(path)
        return None

    # ---------- ADMIN ----------

    def clear(self):
        for d in (self.history_dir, self.info_dir):
            for f in os.listdir(d):
                try:
                    os.remove(os.path.join(d, f))
                except Exception as e:
                    logger.warning("clear cache: cannot remove %s: %s", f, e)

    def stats(self) -> dict:
        return {
            "history_files": len(os.listdir(self.history_dir)),
            "info_files": len(os.listdir(self.info_dir)),
            "cache_dir": self.cache_dir,
            "market_open": is_market_open(),
            "effective_ttl_note": "TTL diperpanjang min 6 jam saat pasar tutup",
        }
