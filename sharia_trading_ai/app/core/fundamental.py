"""
Analisa Fundamental — "6 Magic Number" (modul hal. 9-12).

Sumber utama: master_data_syariah.csv terkurasi (akurat untuk IDX). Bila ticker
tidak ada di master data, fallback ke yfinance.

  1. EPS QnQ growth >= 25%   2. ROA > 15%   3. ROE > 15%
  4. DER < 1 (100%)          5. PBV < 1     6. PER < 10x
  Bonus: Dividend Yield > 7% · Intrinsic Value (BVPS > MP = undervalue)
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import FUND
from app.data import master_data, provider

EPS_GROWTH_MIN = 25.0  # EPS QnQ growth (CAN SLIM C) sebagai kriteria EPS


def _normalize_pct(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value * 100, 2) if abs(value) <= 1 else round(value, 2)


def _crit(name: str, value: Optional[float], passed: Optional[bool], target: str, unit: str = "") -> dict:
    disp = "n/a" if value is None else f"{value}{unit}"
    return {"kriteria": name, "nilai": disp, "target": target, "lolos": passed}


def _metrics(ticker: str, info: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Ambil metrik dari master data (utama) atau yfinance (fallback)."""
    md = master_data.metrics(ticker)
    if md:
        return {
            "eps_growth": md["eps_growth"], "roa": md["roa"], "roe": md["roe"],
            "der": (md["der"] / 100) if md["der"] is not None else None,  # % -> rasio
            "pbv": md["pbv"], "per": md["per"], "dy": md["dividend_yield"],
            "bvps": md["bvps"], "mp": md["market_price"], "source": "master_data",
        }
    # fallback yfinance
    info = info if info is not None else provider.get_info(ticker)
    d2e = info.get("debtToEquity")
    pbv = info.get("priceToBook")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    bvps = info.get("bookValue")
    if (pbv is None or pbv > 100) and price and bvps and bvps > 0:
        pbv = round(price / bvps, 2)
    if pbv is not None and (pbv <= 0 or pbv > 100):
        pbv = None
    return {
        "eps_growth": None,  # yfinance tak menyediakan EPS QnQ andal
        "roa": _normalize_pct(info.get("returnOnAssets")),
        "roe": _normalize_pct(info.get("returnOnEquity")),
        "der": round(d2e / 100, 2) if d2e is not None else None,
        "pbv": pbv, "per": info.get("trailingPE"),
        "dy": _normalize_pct(info.get("dividendYield")),
        "bvps": bvps, "mp": price, "source": "yfinance",
    }


def evaluate_fundamental(ticker: str, info: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    ticker = ticker.upper()
    m = _metrics(ticker, info)
    eps, roa, roe = m["eps_growth"], m["roa"], m["roe"]
    der, pbv, per, dy = m["der"], m["pbv"], m["per"], m["dy"]
    bvps, mp = m["bvps"], m["mp"]

    checks = [
        _crit("EPS QnQ growth", eps, (eps >= EPS_GROWTH_MIN) if eps is not None else None,
              f">= {EPS_GROWTH_MIN}%", "%"),
        _crit("ROA", roa, (roa > FUND.ROA_MIN) if roa is not None else None, f"> {FUND.ROA_MIN}%", "%"),
        _crit("ROE", roe, (roe > FUND.ROE_MIN) if roe is not None else None, f"> {FUND.ROE_MIN}%", "%"),
        _crit("DER", der, (der < FUND.DER_MAX) if der is not None else None, f"< {FUND.DER_MAX}", "x"),
        _crit("PBV", pbv, (pbv < FUND.PBV_MAX) if pbv is not None else None, f"< {FUND.PBV_MAX}", "x"),
        _crit("PER", per, (per < FUND.PER_MAX) if per is not None else None, f"< {FUND.PER_MAX}x", "x"),
    ]
    bonus = _crit("Dividend Yield (bonus)", dy,
                  (dy > FUND.DIVIDEND_YIELD_MIN) if dy is not None else None,
                  f"> {FUND.DIVIDEND_YIELD_MIN}%", "%")

    # Intrinsic value (BVPS > MP = undervalue)
    intrinsic = None
    if bvps is not None and mp is not None and mp > 0:
        intrinsic = bool(bvps > mp)
    undervalue = (pbv < 1.0) if pbv is not None else intrinsic

    score = sum(1 for c in checks if c["lolos"])
    evaluated = sum(1 for c in checks if c["lolos"] is not None)

    # fundamental_label ala app lama: hitung DY & Intrinsic juga (label BUY/HOLD/AVOID)
    full = score + (1 if bonus["lolos"] is True else 0) + (1 if intrinsic is True else 0)
    full_eval = evaluated + (1 if bonus["lolos"] is not None else 0) + (1 if intrinsic is not None else 0)
    if full_eval == 0:
        fundamental_label = "NO DATA"
    elif full >= 6:
        fundamental_label = "STRONG BUY"
    elif full >= 4:
        fundamental_label = "BUY"
    elif full >= 2:
        fundamental_label = "HOLD"
    else:
        fundamental_label = "AVOID"

    return {
        "ticker": ticker,
        "magic_score": score,
        "magic_total": 6,
        "fundamental_score": score,         # dipakai ranking Leader (CAN SLIM L)
        "fundamental_label": fundamental_label,
        "fund_full_score": full,
        "evaluated": evaluated,
        "bonus_dividend": bonus,
        "undervalue": undervalue,
        "intrinsic_value": intrinsic,
        "checks": checks,
        "source": m["source"],
        "raw": {"eps_qnq": eps, "roa": roa, "roe": roe, "der": der,
                "pbv": pbv, "per": per, "dividend_yield": dy, "bvps": bvps, "mp": mp},
        "verdict": _verdict(score, evaluated),
    }


def _verdict(score: int, evaluated: int) -> str:
    if evaluated == 0:
        return "DATA TIDAK CUKUP"
    if score >= 5:
        return "SANGAT BAIK"
    if score >= 3:
        return "CUKUP"
    return "LEMAH"


# ---- ranking sektor (untuk CAN SLIM L) ----
from functools import lru_cache


@lru_cache(maxsize=1)
def sector_scores() -> dict[str, int]:
    """fundamental_score semua saham di master data (lokal, tanpa jaringan)."""
    out: dict[str, int] = {}
    for t in master_data.tickers():
        try:
            out[t] = evaluate_fundamental(t)["fundamental_score"]
        except Exception:
            out[t] = 0
    return out
