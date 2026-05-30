"""
Global Factor — US Market sebagai Leading Indicator IHSG
=========================================================
US market dipakai BUKAN sebagai instrumen trading langsung, melainkan
faktor sentimen global yang mempengaruhi keputusan entry di IHSG.

Indikator yang dipantau:
  ^GSPC    — S&P 500 (sentimen risk-on/off paling broad)
  ^IXIC    — Nasdaq Composite (tech/growth sentiment)
  ^VIX     — Volatility Index (fear gauge)
  DX-Y.NYB — Dollar Index (rupiah strength → IHSG flow)
  ^TNX     — US 10Y Treasury Yield (capital flow EM vs DM)

Composite Risk-On Score (0-100):
  SPX trend (vs MA50)   : 25 pts max  (above MA50 strong → +25)
  VIX level             : 25 pts max  (<15 → +25, >30 → 0)
  DXY trend (vs MA50)   : 20 pts max  (below MA50 lemah → +20)
  US10Y level/trend     : 15 pts max  (<4.5% & turun → +15)
  Nasdaq trend (vs MA50): 15 pts max  (above MA50 → +15)

Status:
  score ≥ 65  → RISK_ON   (entry IHSG boleh agresif)
  35 < score  → NEUTRAL
  score ≤ 35  → RISK_OFF  (perkuat cash & emas, tahan entry)

Influence multiplier untuk threshold trading IHSG:
  RISK_ON  → 1.20  (turunkan threshold entry, lebih agresif)
  NEUTRAL  → 1.00
  RISK_OFF → 0.75  (naikkan threshold entry, lebih defensif)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


TICKERS = {
    "spx":    "^GSPC",
    "nasdaq": "^IXIC",
    "vix":    "^VIX",
    "dxy":    "DX-Y.NYB",
    "us10y":  "^TNX",
}

# Thresholds
VIX_CALM     = 15.0
VIX_NORMAL   = 20.0
VIX_NERVOUS  = 25.0
VIX_PANIC    = 30.0

US10Y_LOW    = 3.5   # %
US10Y_NORMAL = 4.5   # %
US10Y_HIGH   = 5.0   # %


def _ma(prices, n: int) -> Optional[float]:
    if prices is None or len(prices) < n:
        return None
    try:
        return float(sum(prices[-n:]) / n)
    except (TypeError, ZeroDivisionError):
        return None


def _last(prices) -> Optional[float]:
    if prices is None or len(prices) == 0:
        return None
    try:
        return float(prices[-1])
    except (TypeError, ValueError):
        return None


def _trend_score_vs_ma(last_px: Optional[float], ma50: Optional[float],
                       weight: float, prefer_above: bool = True) -> Dict[str, Any]:
    """
    Skor 0..weight berdasarkan posisi harga vs MA50.

    prefer_above=True  → di atas MA50 = positif (saham, indeks)
    prefer_above=False → di bawah MA50 = positif (DXY, VIX, yield)
    """
    if last_px is None or ma50 is None or ma50 <= 0:
        return {"score": weight * 0.5, "delta_pct": None,
                "status": "N/A", "weight": weight}
    delta_pct = (last_px - ma50) / ma50 * 100
    if prefer_above:
        # +5% di atas MA = full score; -5% = nol
        norm = max(-1.0, min(1.0, delta_pct / 5.0))
        score = weight * (0.5 + norm * 0.5)
        status = "UP" if delta_pct > 0 else "DOWN"
    else:
        norm = max(-1.0, min(1.0, -delta_pct / 5.0))
        score = weight * (0.5 + norm * 0.5)
        status = "BEARISH$" if delta_pct > 0 else "BULLISH$"
    return {
        "score": round(score, 2),
        "delta_pct": round(delta_pct, 2),
        "status": status,
        "weight": weight,
    }


def _vix_score(vix_last: Optional[float], weight: float = 25.0) -> Dict[str, Any]:
    """Lower VIX = higher score (risk-on). >30 = 0 pts; <15 = full pts."""
    if vix_last is None:
        return {"score": weight * 0.5, "level": None, "regime": "N/A", "weight": weight}
    if vix_last <= VIX_CALM:
        regime = "CALM"; ratio = 1.0
    elif vix_last <= VIX_NORMAL:
        regime = "NORMAL"
        ratio = 1.0 - (vix_last - VIX_CALM) / (VIX_NORMAL - VIX_CALM) * 0.3   # 1.0 → 0.7
    elif vix_last <= VIX_NERVOUS:
        regime = "NERVOUS"
        ratio = 0.7 - (vix_last - VIX_NORMAL) / (VIX_NERVOUS - VIX_NORMAL) * 0.3  # 0.7 → 0.4
    elif vix_last <= VIX_PANIC:
        regime = "FEAR"
        ratio = 0.4 - (vix_last - VIX_NERVOUS) / (VIX_PANIC - VIX_NERVOUS) * 0.3   # 0.4 → 0.1
    else:
        regime = "PANIC"; ratio = 0.0
    return {
        "score": round(weight * ratio, 2),
        "level": round(vix_last, 2),
        "regime": regime,
        "weight": weight,
    }


def _us10y_score(yld_last: Optional[float], yld_ma20: Optional[float],
                 weight: float = 15.0) -> Dict[str, Any]:
    """
    US10Y rendah & turun → risk-on (capital flow ke EM).
    Catatan: ^TNX di yfinance dalam unit basis-point/10 (mis 42.5 = 4.25%).
    """
    if yld_last is None:
        return {"score": weight * 0.5, "yield_pct": None, "regime": "N/A", "weight": weight}
    # Auto-normalize: kalau angka > 20 asumsi unit yfinance (10x)
    yld_pct = yld_last / 10.0 if yld_last > 20 else yld_last

    if yld_pct <= US10Y_LOW:
        regime = "LOW"; ratio = 1.0
    elif yld_pct <= US10Y_NORMAL:
        regime = "NORMAL"
        ratio = 1.0 - (yld_pct - US10Y_LOW) / (US10Y_NORMAL - US10Y_LOW) * 0.3
    elif yld_pct <= US10Y_HIGH:
        regime = "HIGH"
        ratio = 0.7 - (yld_pct - US10Y_NORMAL) / (US10Y_HIGH - US10Y_NORMAL) * 0.4
    else:
        regime = "VERY_HIGH"; ratio = 0.2

    # Bonus/penalty kalau yield turun vs MA20 (capital flow rotasi ke EM)
    if yld_ma20 is not None:
        ma20_pct = yld_ma20 / 10.0 if yld_ma20 > 20 else yld_ma20
        if ma20_pct > 0:
            delta = (yld_pct - ma20_pct) / ma20_pct
            # turun 5% → +0.1 ratio bonus; naik 5% → -0.1
            ratio = max(0.0, min(1.0, ratio - delta * 2.0))
    return {
        "score": round(weight * ratio, 2),
        "yield_pct": round(yld_pct, 3),
        "regime": regime,
        "weight": weight,
    }


def compute_global_factor(cache_obj=None,
                          spx_hist=None, nasdaq_hist=None, vix_hist=None,
                          dxy_hist=None, us10y_hist=None) -> Dict[str, Any]:
    """
    Hitung composite Global Risk Factor.

    Mode 1 (recommended): pass `cache_obj` (instance modules.cache.Cache).
        Fungsi akan fetch ^GSPC, ^IXIC, ^VIX, DX-Y.NYB, ^TNX otomatis.

    Mode 2 (testing): pass setiap hist sebagai list[float] close prices
        (urutan kronologis, terbaru di akhir).

    Returns:
        {
          "status": "RISK_ON" | "NEUTRAL" | "RISK_OFF",
          "score": 0..100,
          "influence_multiplier": 0.75..1.20,
          "components": {
              "spx": {...}, "nasdaq": {...}, "vix": {...},
              "dxy": {...}, "us10y": {...},
          },
          "narrative": str,
          "errors": [list of fetch errors, if any],
        }
    """
    errors = []

    def _prices_from_hist_df(df):
        if df is None or df.empty or "Close" not in df.columns:
            return None
        try:
            return [float(x) for x in df["Close"].dropna().tolist()]
        except Exception:
            return None

    # Fetch via cache jika tidak di-pass manual
    if cache_obj is not None:
        try:
            if spx_hist is None:
                spx_hist = _prices_from_hist_df(
                    cache_obj.get_history(TICKERS["spx"], period="1y", ttl_minutes=240)
                )
        except Exception as e:
            errors.append(f"spx fetch: {e}")
        try:
            if nasdaq_hist is None:
                nasdaq_hist = _prices_from_hist_df(
                    cache_obj.get_history(TICKERS["nasdaq"], period="1y", ttl_minutes=240)
                )
        except Exception as e:
            errors.append(f"nasdaq fetch: {e}")
        try:
            if vix_hist is None:
                vix_hist = _prices_from_hist_df(
                    cache_obj.get_history(TICKERS["vix"], period="3mo", ttl_minutes=240)
                )
        except Exception as e:
            errors.append(f"vix fetch: {e}")
        try:
            if dxy_hist is None:
                dxy_hist = _prices_from_hist_df(
                    cache_obj.get_history(TICKERS["dxy"], period="1y", ttl_minutes=240)
                )
        except Exception as e:
            errors.append(f"dxy fetch: {e}")
        try:
            if us10y_hist is None:
                us10y_hist = _prices_from_hist_df(
                    cache_obj.get_history(TICKERS["us10y"], period="3mo", ttl_minutes=240)
                )
        except Exception as e:
            errors.append(f"us10y fetch: {e}")

    # Compute per-indicator scores
    spx_last = _last(spx_hist); spx_ma50 = _ma(spx_hist, 50)
    spx = _trend_score_vs_ma(spx_last, spx_ma50, weight=25.0, prefer_above=True)
    spx["last"] = round(spx_last, 2) if spx_last else None
    spx["ma50"] = round(spx_ma50, 2) if spx_ma50 else None

    nas_last = _last(nasdaq_hist); nas_ma50 = _ma(nasdaq_hist, 50)
    nasdaq = _trend_score_vs_ma(nas_last, nas_ma50, weight=15.0, prefer_above=True)
    nasdaq["last"] = round(nas_last, 2) if nas_last else None
    nasdaq["ma50"] = round(nas_ma50, 2) if nas_ma50 else None

    vix_last = _last(vix_hist)
    vix = _vix_score(vix_last, weight=25.0)

    dxy_last = _last(dxy_hist); dxy_ma50 = _ma(dxy_hist, 50)
    dxy = _trend_score_vs_ma(dxy_last, dxy_ma50, weight=20.0, prefer_above=False)
    dxy["last"] = round(dxy_last, 2) if dxy_last else None
    dxy["ma50"] = round(dxy_ma50, 2) if dxy_ma50 else None

    yld_last = _last(us10y_hist); yld_ma20 = _ma(us10y_hist, 20)
    us10y = _us10y_score(yld_last, yld_ma20, weight=15.0)

    total_score = round(
        spx["score"] + nasdaq["score"] + vix["score"] +
        dxy["score"] + us10y["score"], 2
    )

    # Status & multiplier
    if total_score >= 65:
        status, mult = "RISK_ON", 1.20
    elif total_score >= 35:
        status, mult = "NEUTRAL", 1.00
    else:
        status, mult = "RISK_OFF", 0.75

    narrative = _narrate(status, total_score, spx, vix, dxy, us10y, nasdaq)

    return {
        "status": status,
        "score": total_score,
        "max_score": 100.0,
        "influence_multiplier": mult,
        "components": {
            "spx":    spx,
            "nasdaq": nasdaq,
            "vix":    vix,
            "dxy":    dxy,
            "us10y":  us10y,
        },
        "narrative": narrative,
        "errors": errors,
    }


def _narrate(status: str, score: float, spx: Dict, vix: Dict,
             dxy: Dict, us10y: Dict, nasdaq: Dict) -> str:
    """Compose human-readable narrative dari komponen."""
    parts = []
    if spx.get("status") == "UP":
        parts.append(f"S&P 500 di atas MA50 ({spx.get('delta_pct', 0):+.1f}%)")
    elif spx.get("status") == "DOWN":
        parts.append(f"S&P 500 di bawah MA50 ({spx.get('delta_pct', 0):+.1f}%)")
    if vix.get("regime") not in (None, "N/A"):
        parts.append(f"VIX {vix.get('level','?')} ({vix.get('regime')})")
    # Catatan: BEARISH$ = DXY naik = USD kuat = tekanan ke rupiah.
    # BULLISH$ = DXY turun = USD lemah = rupiah berpotensi menguat.
    if dxy.get("status") == "BEARISH$":
        parts.append(f"DXY kuat ({dxy.get('delta_pct', 0):+.1f}% vs MA50) → tekanan rupiah")
    elif dxy.get("status") == "BULLISH$":
        parts.append(f"DXY lemah ({dxy.get('delta_pct', 0):+.1f}% vs MA50) → rupiah bisa menguat")
    if us10y.get("regime") not in (None, "N/A"):
        parts.append(f"US10Y {us10y.get('yield_pct', '?')}% ({us10y.get('regime')})")
    if nasdaq.get("status") == "UP":
        parts.append(f"Nasdaq up ({nasdaq.get('delta_pct', 0):+.1f}%)")

    base = " | ".join(parts) if parts else "Data global terbatas"

    if status == "RISK_ON":
        verdict = (f"🟢 RISK-ON (score {score:.0f}/100) — sentimen global mendukung, "
                   f"threshold entry IHSG boleh dilonggarkan ×1.20.")
    elif status == "RISK_OFF":
        verdict = (f"🔴 RISK-OFF (score {score:.0f}/100) — perkuat cash & emas, "
                   f"threshold entry IHSG diketatkan ×0.75. Tahan entry baru.")
    else:
        verdict = (f"🟡 NEUTRAL (score {score:.0f}/100) — pasar global mixed, "
                   f"pakai threshold default ×1.00.")
    return f"{verdict}  Detail: {base}."
