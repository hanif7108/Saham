"""
Master Data Syariah — data fundamental TERKURASI (dari app lama Mac Mini).

Sumber: master_data_syariah.csv (google+yfinance+stockbit) — 75 saham DES/ISSI
dengan EPS QnQ, ROA, ROE, NPM, PER, PBV, DER, PEG, BVPS, MP, Free Float, Dividend
Yield. Jauh lebih akurat untuk saham IDX dibanding yfinance murni (yang sering
n/a untuk EPS kuartal, PBV, free float).

Dipakai sebagai sumber utama fundamental & universe; yfinance tetap untuk harga
historis/teknikal.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from app.config import DATA_DIR

CSV = DATA_DIR / "master_data_syariah.csv"


def _f(v: Any) -> Optional[float]:
    """Parse '17.5%', '12.3x', '1,234', 'N/A' -> float|None."""
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace("x", "").replace("X", "").replace(",", "")
    if s in ("", "N/A", "ERROR", "NaN", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _rows() -> list[dict[str, str]]:
    if not CSV.exists():
        return []
    with open(CSV, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("Ticker")]


def available() -> bool:
    return len(_rows()) > 0


@lru_cache(maxsize=1)
def _by_ticker() -> dict[str, dict[str, str]]:
    return {r["Ticker"].strip().upper(): r for r in _rows()}


def tickers() -> list[str]:
    return [r["Ticker"].strip().upper() for r in _rows()]


def universe() -> list[dict[str, str]]:
    return [{"ticker": r["Ticker"].strip().upper(),
             "name": r.get("Nama Perusahaan", "").strip(),
             "sector": r.get("Sektor", "").strip()} for r in _rows()]


def sector_of(ticker: str) -> Optional[str]:
    r = _by_ticker().get(ticker.upper())
    return r.get("Sektor", "").strip() if r else None


def metrics(ticker: str) -> Optional[dict[str, Any]]:
    """Fundamental terkurasi 1 saham (nilai sudah di-parse ke float)."""
    r = _by_ticker().get(ticker.upper())
    if not r:
        return None
    return {
        "ticker": ticker.upper(),
        "name": r.get("Nama Perusahaan", "").strip(),
        "sector": r.get("Sektor", "").strip(),
        "eps_growth": _f(r.get("EPS QnQ")),       # EPS QnQ % (untuk CAN SLIM C)
        "roa": _f(r.get("ROA")),
        "roe": _f(r.get("ROE")),
        "npm": _f(r.get("NPM")),
        "per": _f(r.get("PER")),
        "pbv": _f(r.get("PBV")),
        "der": _f(r.get("DER")),                  # dalam persen (mis 19.54 = 19.54%)
        "peg": _f(r.get("PEG")),
        "bvps": _f(r.get("BVPS")),
        "market_price": _f(r.get("MP")),
        "free_float": _f(r.get("Free Float")),
        "dividend_yield": _f(r.get("Dividend Yield")),
        "source": r.get("Source", "").strip(),
    }
