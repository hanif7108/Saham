"""
Analisa Fundamental — "6 Magic Number" (modul hal. 9-12).

Sumber metrik dipilih lewat settings.data_source (default "hybrid"):
TradingView live -> master_data CSV -> yfinance. TradingView memberi angka IDX
yang segar & akurat; master_data/yfinance jadi jaring pengaman. Set data_source
ke "master_data" untuk kembali ke perilaku lama.

  1. EPS QnQ growth >= 25%   2. ROA > 15%   3. ROE > 15%
  4. DER < 1 (100%)          5. PBV < 1     6. PER < 10x
  Bonus: Dividend Yield > 7% · Intrinsic Value (BVPS > MP = undervalue)
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import FUND, settings
from app.data import master_data, provider, tradingview_provider

EPS_GROWTH_MIN = 25.0  # EPS QnQ growth (CAN SLIM C) sebagai kriteria EPS

# Field metrik yang dievaluasi 6 Magic Number (untuk pengisian celah mode hybrid).
_FILLABLE = ("eps_growth", "roa", "roe", "der", "pbv", "per", "dy", "bvps", "mp")


def _normalize_pct(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value * 100, 2) if abs(value) <= 1 else round(value, 2)


def _crit(name: str, value: Optional[float], passed: Optional[bool], target: str, unit: str = "") -> dict:
    disp = "n/a" if value is None else f"{value}{unit}"
    return {"kriteria": name, "nilai": disp, "target": target, "lolos": passed}


def _md_shape(ticker: str) -> Optional[dict[str, Any]]:
    """Metrik dari master_data CSV (DER % -> rasio), atau None bila tak ada."""
    md = master_data.metrics(ticker)
    if not md:
        return None
    return {
        "eps_growth": md["eps_growth"], "roa": md["roa"], "roe": md["roe"],
        "der": (md["der"] / 100) if md["der"] is not None else None,  # % -> rasio
        "pbv": md["pbv"], "per": md["per"], "dy": md["dividend_yield"],
        "bvps": md["bvps"], "mp": md["market_price"], "source": "master_data",
    }


def _tv_shape(ticker: str) -> Optional[dict[str, Any]]:
    """Metrik LIVE dari TradingView (DER sudah rasio), atau None bila gagal."""
    try:
        tv = tradingview_provider.metrics(ticker)
    except Exception:  # noqa: BLE001 — jaringan/parsing: jangan ganggu funnel
        return None
    if not tv:
        return None
    return {
        "eps_growth": tv.get("eps_growth"), "roa": tv.get("roa"), "roe": tv.get("roe"),
        "der": tv.get("der"), "pbv": tv.get("pbv"), "per": tv.get("per"),
        "dy": tv.get("dy"), "bvps": tv.get("bvps"), "mp": tv.get("mp"),
        "source": "tradingview",
        "tv_extra": {
            "recommend_all": tv.get("recommend_all"),
            "recommend_label": tv.get("recommend_label"),
            "recommend_ma": tv.get("recommend_ma"),
            "recommend_other": tv.get("recommend_other"),
            "eps_yoy": tv.get("eps_yoy"),
        },
    }


def _yf_shape(ticker: str, info: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Metrik dari yfinance (fallback terakhir)."""
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


def _fill_gaps(base: dict[str, Any], extra: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Isi field yang None pada base dari extra; tandai sumber gabungan."""
    if not extra:
        return base
    filled = False
    for k in _FILLABLE:
        if base.get(k) is None and extra.get(k) is not None:
            base[k] = extra[k]
            filled = True
    if filled:
        base["source"] = f"{base.get('source', '?')}+{extra.get('source', '?')}"
    return base


def _metrics(ticker: str, info: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Pilih sumber metrik sesuai settings.data_source (default: master_data)."""
    mode = (settings.data_source or "master_data").lower()

    if mode == "yfinance":
        return _yf_shape(ticker, info)

    if mode == "tradingview":
        return _tv_shape(ticker) or _md_shape(ticker) or _yf_shape(ticker, info)

    if mode == "hybrid":
        base = _tv_shape(ticker)
        if base is None:
            return _md_shape(ticker) or _yf_shape(ticker, info)
        base = _fill_gaps(base, _md_shape(ticker))   # isi celah dari CSV lokal (gratis)
        # Lengkapi dari yfinance HANYA bila info sudah tersedia (mis. dari funnel),
        # supaya tidak memicu request jaringan per-ticker saat ranking massal.
        if info is not None and any(base.get(k) is None for k in _FILLABLE):
            base = _fill_gaps(base, _yf_shape(ticker, info))
        return base

    # default "master_data": perilaku lama (master_data -> yfinance)
    return _md_shape(ticker) or _yf_shape(ticker, info)


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
        "tradingview": m.get("tv_extra"),   # rekomendasi teknikal TV utk cross-check (None bila tak dipakai)
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
    """fundamental_score semua saham (dipakai ranking Leader CAN SLIM L)."""
    tickers = master_data.tickers()
    # Pra-muat TradingView SATU batch supaya per-ticker di bawah baca cache, bukan
    # 75 request terpisah (graceful: diabaikan bila gagal / sumber bukan TV).
    if (settings.data_source or "").lower() in ("tradingview", "hybrid"):
        try:
            tradingview_provider.scan_fundamentals(tickers)
        except Exception:  # noqa: BLE001
            pass
    out: dict[str, int] = {}
    for t in tickers:
        try:
            out[t] = evaluate_fundamental(t)["fundamental_score"]
        except Exception:
            out[t] = 0
    return out
