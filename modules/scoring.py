"""
Fundamental Scoring Module — STRICT (sesuai panduan Doddy Eka Putra)
==================================================================
Menghitung skor fundamental berbasis "6 Magic Numbers" sesuai
Sharia Investment Module:

  1. EPS              positive + growing (CAN SLIM C: > 25% QnQ)
  2. ROA              > 15%
  3. ROE              > 15%
  4. DER              < 100%
  5. PBV              < 1
  6. PER              < 10x
  7. Bonus: Dividend Yield > 7%
  8. Bonus: Intrinsic Value (BVPS > MP = undervalue)

Scoring berbasis sektor benchmark: jika data sektor tersedia, kriteria
PER & PBV dibandingkan ke median sektor (lebih adil daripada threshold tetap).

Output: skor 0..8, bintang (max 5), narasi alasan, label CANSLIM-friendly.
"""

import warnings
from typing import Dict, List, Optional

import pandas as pd

# Suppress "Mean of empty slice" warning saat sektor hanya punya 1 ticker
warnings.filterwarnings("ignore", category=RuntimeWarning,
                         message="Mean of empty slice")


# ----------------------------- HELPERS ----------------------------- #

def _to_float(val) -> Optional[float]:
    """Konversi nilai (str / float / None) ke float, support '17.5%', '12.3x'."""
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.upper() in {"N/A", "ERROR", "NAN"}:
        return None
    s = s.replace("%", "").replace("x", "").replace("X", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# ----------------------------- BENCHMARK ----------------------------- #

def compute_sector_benchmarks(master_df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """
    Hitung median per-sektor untuk PER, PBV, ROE, DER.
    Berguna untuk scoring relatif (lebih adil per sektor).
    """
    if master_df is None or master_df.empty or "Sektor" not in master_df.columns:
        return {}

    df = master_df.copy()
    for col in ("PER", "PBV", "ROE", "DER"):
        if col in df.columns:
            df[col] = df[col].apply(_to_float)

    benchmarks = {}
    for sector, group in df.groupby("Sektor"):
        if sector in (None, "", "N/A", "ERROR"):
            continue
        benchmarks[sector] = {
            "PER_median": group["PER"].median() if "PER" in group else None,
            "PBV_median": group["PBV"].median() if "PBV" in group else None,
            "ROE_median": group["ROE"].median() if "ROE" in group else None,
            "DER_median": group["DER"].median() if "DER" in group else None,
            "n_samples": int(len(group))
        }
    return benchmarks


# ----------------------------- SCORING ----------------------------- #

def score_fundamentals(
    metrics: Dict,
    sector: Optional[str] = None,
    benchmarks: Optional[Dict[str, Dict[str, float]]] = None
) -> Dict:
    """
    Hitung skor fundamental dari metrics dict.

    Input metrics keys (boleh string '17.5%' atau float):
        eps_growth (decimal, mis 0.25 = 25%, atau '25%')
        roe (decimal atau '%')
        npm / profit_margin (decimal)
        der (% atau decimal-as-percent)
        per (x)
        pbv (x)
        peg
        dividend_yield (decimal)

    Returns:
        {
            'score': int (0..8),
            'stars': str (max 5 bintang),
            'label': str,                # 'STRONG BUY' | 'BUY' | 'HOLD' | 'AVOID'
            'reasons_pass': List[str],
            'reasons_fail': List[str],
            'detail': Dict[str, bool]
        }
    """
    benchmarks = benchmarks or {}
    sec_bench = benchmarks.get(sector or "", {})

    eps_g = _to_float(metrics.get("eps_growth"))
    roe = _to_float(metrics.get("roe"))
    roa = _to_float(metrics.get("roa"))
    der = _to_float(metrics.get("der"))
    per = _to_float(metrics.get("per"))
    pbv = _to_float(metrics.get("pbv"))
    div_y = _to_float(metrics.get("dividend_yield"))
    bvps = _to_float(metrics.get("bvps"))            # Book Value per Share
    market_price = _to_float(metrics.get("market_price"))

    # Normalisasi: kadang yfinance returnOnEquity = 0.17 (decimal),
    # tapi setelah parse dari string '17.5%' kita dapat 17.5. Treat keduanya:
    def _pct(x):
        if x is None:
            return None
        return x if abs(x) > 1.5 else x * 100  # asumsikan kalau < 1.5 berarti decimal

    roe_pct = _pct(roe)
    roa_pct = _pct(roa)
    eps_g_pct = _pct(eps_g)
    div_y_pct = _pct(div_y)

    # DER: yfinance kadang return 'debtToEquity' dalam persen (mis 75 = 75%)
    # atau decimal (0.75). Treat:
    der_pct = der if (der is not None and der > 5) else (der * 100 if der is not None else None)

    detail = {}
    pass_reasons: List[str] = []
    fail_reasons: List[str] = []

    # 1. EPS Growth > 25%
    if eps_g_pct is not None:
        ok = eps_g_pct >= 25
        ok = bool(ok)
        detail["eps_growth"] = ok
        (pass_reasons if ok else fail_reasons).append(
            f"EPS QnQ {eps_g_pct:.1f}% {'≥ 25%' if ok else '< 25%'}"
        )

    # 2. ROA > 15% (sesuai panduan)
    if roa_pct is not None:
        ok = bool(roa_pct >= 15)
        detail["roa"] = ok
        (pass_reasons if ok else fail_reasons).append(
            f"ROA {roa_pct:.1f}% {'≥ 15%' if ok else '< 15%'}"
        )

    # 3. ROE > 15% (sesuai panduan, lebih longgar dari sebelumnya 17)
    if roe_pct is not None:
        ok = bool(roe_pct >= 15)
        detail["roe"] = ok
        (pass_reasons if ok else fail_reasons).append(
            f"ROE {roe_pct:.1f}% {'≥ 15%' if ok else '< 15%'}"
        )

    # 4. DER < 100%
    if der_pct is not None:
        ok = der_pct < 100
        ok = bool(ok)
        detail["der"] = ok
        (pass_reasons if ok else fail_reasons).append(
            f"DER {der_pct:.1f}% {'< 100%' if ok else '≥ 100%'}"
        )

    # 5. PER: pakai sektor median jika ada, kalau tidak threshold 10x
    if per is not None:
        per_med = sec_bench.get("PER_median")
        try:
            per_med = float(per_med) if per_med is not None else None
            if per_med != per_med:  # NaN check
                per_med = None
        except (TypeError, ValueError):
            per_med = None
        threshold = per_med if per_med else 10
        ok = bool(per < threshold)
        detail["per"] = ok
        suffix = f"(median sektor {threshold:.1f}x)" if per_med else "(target <10x)"
        (pass_reasons if ok else fail_reasons).append(
            f"PER {per:.1f}x {suffix}"
        )

    # 6. PBV < 1 (panduan strict — undervalue)
    if pbv is not None:
        ok = bool(pbv < 1.0)
        detail["pbv"] = ok
        suffix = "(< 1 = undervalue)" if ok else "(≥ 1)"
        (pass_reasons if ok else fail_reasons).append(
            f"PBV {pbv:.2f}x {suffix}"
        )

    # 7. Bonus: Dividend Yield > 7% (panduan strict)
    if div_y_pct is not None:
        ok = bool(div_y_pct >= 7)
        detail["div_yield"] = ok
        (pass_reasons if ok else fail_reasons).append(
            f"Div Yield {div_y_pct:.2f}% {'≥ 7%' if ok else '< 7%'}"
        )

    # 8. Bonus: Intrinsic Value (BVPS > MP = undervalue)
    if bvps is not None and market_price is not None and market_price > 0:
        ok = bool(bvps > market_price)
        detail["intrinsic_value"] = ok
        if ok:
            margin = (bvps - market_price) / market_price * 100
            pass_reasons.append(
                f"Intrinsic Value: BVPS {bvps:,.0f} > MP {market_price:,.0f} (undervalue +{margin:.1f}%)"
            )
        else:
            fail_reasons.append(
                f"Intrinsic Value: BVPS {bvps:,.0f} ≤ MP {market_price:,.0f} (overvalue/fair)"
            )

    # Hitung skor
    score = sum(1 for v in detail.values() if v)
    n_evaluated = len(detail)

    # Stars: max 5 (skala dari skor dibandingkan total kriteria yang dievaluasi)
    if n_evaluated == 0:
        stars_count = 0
    else:
        stars_count = min(5, round(score / n_evaluated * 5))
    stars = "⭐" * stars_count if stars_count > 0 else "❓"

    # Label
    if n_evaluated == 0:
        label = "NO DATA"
    elif score >= 6:
        label = "STRONG BUY"
    elif score >= 4:
        label = "BUY"
    elif score >= 2:
        label = "HOLD"
    else:
        label = "AVOID"

    return {
        "score": int(score),
        "max_score": int(n_evaluated),
        "stars": stars,
        "stars_count": stars_count,
        "label": label,
        "reasons_pass": pass_reasons,
        "reasons_fail": fail_reasons,
        "detail": detail
    }


def combine_signals(fundamental: Dict, technical: Dict) -> Dict:
    """
    Gabungkan sinyal fundamental + teknikal jadi rekomendasi akhir.

    Logika:
        - Fundamental BUY/STRONG BUY + Teknikal BUY → STRONG BUY
        - Fundamental BUY + Teknikal HOLD → ACCUMULATE
        - Fundamental HOLD + Teknikal BUY → SPECULATIVE BUY
        - Fundamental AVOID → AVOID terlepas teknikal
        - Teknikal SELL + posisi loss → CUT LOSS
    """
    f_label = fundamental.get("label", "NO DATA")
    t_signal = technical.get("signal", "NO DATA")

    if f_label == "AVOID":
        final = "AVOID"
        css = "sell"
    elif f_label == "STRONG BUY" and t_signal == "BUY":
        final = "STRONG BUY"
        css = "buy"
    elif f_label in ("STRONG BUY", "BUY") and t_signal == "BUY":
        final = "BUY"
        css = "buy"
    elif f_label in ("STRONG BUY", "BUY"):
        final = "ACCUMULATE"
        css = "warning"
    elif f_label == "HOLD" and t_signal == "BUY":
        final = "SPECULATIVE BUY"
        css = "warning"
    elif t_signal == "SELL":
        final = "WATCH (Tech Weak)"
        css = "warning"
    else:
        final = "HOLD"
        css = "hold"

    return {
        "final_signal": final,
        "css_class": css,
        "fundamental_label": f_label,
        "technical_signal": t_signal,
        "fundamental_score": fundamental.get("score", 0),
        "fundamental_max": fundamental.get("max_score", 0),
        "technical_score": technical.get("score", 0),
        "stars": fundamental.get("stars", "❓"),
    }


# ----------------------------- TRADING SCORE (Multi-Factor) ----------------------------- #

# Bobot per faktor (total 100%)
WEIGHT_TECHNICAL = 40.0   # %
WEIGHT_GLOBAL    = 30.0   # %
WEIGHT_SECTOR    = 20.0   # %
WEIGHT_SYARIAH   = 10.0   # %

# Threshold rekomendasi
TS_ENTRY     = 70.0   # ≥ 70 → ENTRY
TS_WATCHLIST = 50.0   # 50-69 → WATCHLIST
# < 50 → HOLD


def compute_trading_score(
    stock: Dict,
    global_factor: Optional[Dict] = None,
    sector_benchmark: Optional[Dict] = None,
) -> Dict:
    """
    Hitung Trading Score multi-factor (0..100) untuk satu saham.

    Formula:
        TS = (Teknikal × 40%) + (Global × 30%) + (Sektor × 20%) + (Syariah × 10%)

    Args:
        stock: dict ranking dengan minimal keys:
            - technical_score (0..max, biasanya 0..5)
            - technical_max (default 5)
            - fundamental_label ('STRONG BUY', 'BUY', 'HOLD', 'AVOID')
            - rsi, ma_cross (untuk bonus teknikal)
            - sector (string)
            - sector_perf_pct (opsional — return sektor n-day)
        global_factor: output dari modules.global_factor.compute_global_factor()
            akan diambil .score (0..100) dan .influence_multiplier
        sector_benchmark: dict per sektor dari compute_sector_benchmarks(),
            dipakai jika sector_perf_pct tidak tersedia.

    Returns:
        {
          "score": 0..100,
          "recommendation": "ENTRY" | "WATCHLIST" | "HOLD",
          "breakdown": {
              "technical": pts (0..40),
              "global":    pts (0..30),
              "sector":    pts (0..20),
              "syariah":   pts (0..10),
          },
          "threshold_used": effective ENTRY threshold (after global influence),
          "rationale": str  # one-liner penjelasan
        }
    """
    # --- 1. Technical (40%) ---
    tech_score = float(stock.get("technical_score") or 0)
    tech_max = float(stock.get("technical_max") or 5)
    if tech_max <= 0:
        tech_max = 5
    tech_pts = (tech_score / tech_max) * WEIGHT_TECHNICAL
    # Bonus: golden cross + RSI di sweet-spot (40-60) → +10% relatif
    ma_cross = str(stock.get("ma_cross") or "").upper()
    rsi = _to_float(stock.get("rsi"))
    if ma_cross == "GOLDEN" and rsi is not None and 40 <= rsi <= 60:
        tech_pts = min(WEIGHT_TECHNICAL, tech_pts * 1.10)
    # Penalty: death cross atau RSI > 75 → -15%
    if ma_cross == "DEATH" or (rsi is not None and rsi > 75):
        tech_pts = tech_pts * 0.85

    # --- 2. Global Factor (30%) ---
    if global_factor is None:
        # No data → asumsi NEUTRAL
        global_pts = WEIGHT_GLOBAL * 0.5   # 15
        global_status = "N/A"
        global_score = 50.0
        influence_mult = 1.0
    else:
        global_score = float(global_factor.get("score") or 50)
        global_status = str(global_factor.get("status") or "NEUTRAL")
        influence_mult = float(global_factor.get("influence_multiplier") or 1.0)
        global_pts = (global_score / 100.0) * WEIGHT_GLOBAL

    # --- 3. Sector Momentum (20%) ---
    sector = stock.get("sector") or ""
    sector_perf = _to_float(stock.get("sector_perf_pct"))
    if sector_perf is None and sector_benchmark and sector in sector_benchmark:
        sector_perf = _to_float(sector_benchmark[sector].get("perf_pct"))
    if sector_perf is None:
        sector_pts = WEIGHT_SECTOR * 0.5   # default 10
    else:
        # +5% perf 30-day → full pts; -5% → 0 pts; linear in between
        norm = max(-1.0, min(1.0, sector_perf / 5.0))
        sector_pts = WEIGHT_SECTOR * (0.5 + norm * 0.5)

    # --- 4. Syariah Compliance (10%) ---
    fund_label = str(stock.get("fundamental_label") or "").upper()
    if fund_label in ("STRONG BUY",):
        syariah_pts = WEIGHT_SYARIAH * 1.0
    elif fund_label in ("BUY",):
        syariah_pts = WEIGHT_SYARIAH * 0.85
    elif fund_label in ("HOLD",):
        syariah_pts = WEIGHT_SYARIAH * 0.5
    elif fund_label in ("AVOID",):
        syariah_pts = 0.0
    else:
        syariah_pts = WEIGHT_SYARIAH * 0.4    # NO DATA / unknown

    # --- 5. Composite & recommendation ---
    total = round(tech_pts + global_pts + sector_pts + syariah_pts, 2)

    # Effective threshold disesuaikan global influence
    # RISK_OFF (mult 0.75) → naikkan threshold (lebih ketat); RISK_ON (1.20) → turunkan
    threshold_used = round(TS_ENTRY / influence_mult, 2)

    if total >= threshold_used:
        rec = "ENTRY"
    elif total >= TS_WATCHLIST:
        rec = "WATCHLIST"
    else:
        rec = "HOLD"

    # Rationale singkat
    rationale = (
        f"Tech {tech_pts:.0f}/40 + Global {global_pts:.0f}/30 ({global_status}) "
        f"+ Sektor {sector_pts:.0f}/20 + Syariah {syariah_pts:.0f}/10 = {total:.0f} "
        f"(threshold {threshold_used:.0f})"
    )

    return {
        "score": total,
        "recommendation": rec,
        "breakdown": {
            "technical": round(tech_pts, 2),
            "global":    round(global_pts, 2),
            "sector":    round(sector_pts, 2),
            "syariah":   round(syariah_pts, 2),
        },
        "global_status": global_status,
        "global_score": global_score,
        "influence_multiplier": influence_mult,
        "threshold_used": threshold_used,
        "rationale": rationale,
    }


if __name__ == "__main__":
    # Smoke test
    sample_metrics = {
        "eps_growth": "30%",
        "roe": "20%",
        "npm": "12%",
        "der": "60%",
        "per": "8x",
        "pbv": "1.2x",
        "peg": "1.0",
        "dividend_yield": "5%"
    }
    result = score_fundamentals(sample_metrics)
    print("=== SMOKE TEST scoring.py ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
