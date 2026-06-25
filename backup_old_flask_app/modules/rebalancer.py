"""
Portfolio Rebalancer — Engine Alokasi Optimal Harian
=====================================================
Menghitung target alokasi modal di empat kelas aset syariah-friendly:
  1. Saham Syariah IDX  — growth asset domestik
  2. Saham Syariah US   — diversifikasi geografis (AAOIFI-screened, direct ownership)
  3. Emas/Perak/Dinar   — safe-haven, hedge inflasi
  4. Cash               — buffer & opportunity reserve

Filosofi (post-patch 2026-05):
  Baseline conservative syariah: 45% IDX, 15% US, 25% emas, 15% cash
  Adjusted by sinyal hari ini:
    A. Arah IHSG (vs MA50)                                  → ±10% IDX
    A2.Arah S&P 500 (vs MA50)                                → ±5% US
    B. Jumlah OVERSOLD_GEM alert (peluang akumulasi)        → +0..5% IDX
    C. Ada CUT_LOSS atau urgent SELL di portfolio            → −5..10% IDX
    D. RSI emas (overbought / oversold)                      → ±5% emas
    E. Cash broker terhadap nilai portfolio (likuiditas)     → adjust cash floor

Output bukan instruksi mutlak — ini sinyal harian yang user evaluasi
sambil mengingat Jalur 7 + DSN-MUI/AAOIFI compliance.

Backward-compat: output tetap punya key "saham" = saham_idx + saham_us
supaya UI lama yang hanya tahu 3-bucket tidak break.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any


# ---------- Baseline & batas alokasi ---------- #
BASELINE = {
    "saham_idx": 0.45,
    "saham_us":  0.15,
    "emas":      0.25,
    "cash":      0.15,
}
MIN_CASH = 0.10        # selalu sisakan ≥10% cash sebagai buffer
MAX_SAHAM_IDX = 0.60   # batas atas IDX
MIN_SAHAM_IDX = 0.20   # minimal exposure IDX
MAX_SAHAM_US = 0.30    # batas atas US
MIN_SAHAM_US = 0.00    # boleh 0 (kalau user belum trade US)
MAX_EMAS = 0.40        # batas atas emas (overweight safe-haven)
MIN_EMAS = 0.10        # selalu ada hedge inflasi

# Legacy alias (untuk kode lama yang import MIN_SAHAM/MAX_SAHAM)
MIN_SAHAM = MIN_SAHAM_IDX + MIN_SAHAM_US
MAX_SAHAM = MAX_SAHAM_IDX + MAX_SAHAM_US


# ---------- Util ---------- #
def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _normalize(alloc: Dict[str, float]) -> Dict[str, float]:
    """Normalisasi agar total = 1.0 sambil hormati batas minimum (4 bucket)."""
    # Apply floors per bucket
    alloc["cash"]       = max(alloc.get("cash", 0), MIN_CASH)
    alloc["saham_idx"]  = _clip(alloc.get("saham_idx", 0), MIN_SAHAM_IDX, MAX_SAHAM_IDX)
    alloc["saham_us"]   = _clip(alloc.get("saham_us", 0), MIN_SAHAM_US, MAX_SAHAM_US)
    alloc["emas"]       = _clip(alloc.get("emas", 0), MIN_EMAS, MAX_EMAS)

    # Re-normalize ke 1.0
    total = alloc["saham_idx"] + alloc["saham_us"] + alloc["emas"] + alloc["cash"]
    if total <= 0:
        return BASELINE.copy()
    return {k: v / total for k, v in alloc.items()}


# ---------- Engine utama ---------- #
def compute_allocation(
    market_status: Optional[Dict] = None,
    alerts_today: Optional[List[Dict]] = None,
    decisions: Optional[Dict] = None,
    gold_signal: Optional[Dict] = None,
    portfolio_value_rp: float = 0.0,
    broker_cash_rp: float = 0.0,
    gold_value_rp: float = 0.0,
    us_portfolio_value_rp: float = 0.0,
    us_market_status: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Hitung target alokasi % saham/emas/cash + narrative.

    Args:
        market_status: {ihsg_close, ihsg_ma50}
        alerts_today:  list of alert dict (type, severity, ticker)
        decisions:     output build_decisions (summary, sell, buy, hold)
        gold_signal:   {rsi, trend, last_price_idr_per_gram}
        portfolio_value_rp: nilai total holdings saham (untuk cash ratio)
        broker_cash_rp:     saldo cash broker (idem)

    Returns:
        {
          "target":   {"saham": 0.65, "emas": 0.20, "cash": 0.15},
          "current":  {"saham": 0.78, "emas": 0.00, "cash": 0.22},
          "delta":    {"saham": -0.13, "emas": +0.20, "cash": -0.07},
          "signals":  [list of (signal_name, direction, weight) yang menggerakan alokasi],
          "verdict":  "🟢 IHSG uptrend + 12 setup oversold — geser cash ke saham",
          "action":   "REBALANCE" | "HOLD_CURRENT" | "DEFENSIVE"
        }
    """
    alloc = BASELINE.copy()
    signals: List[Dict[str, Any]] = []

    # ----- SINYAL A: Arah IHSG vs MA50 ----- #
    ihsg_close = (market_status or {}).get("ihsg_close")
    ihsg_ma50 = (market_status or {}).get("ihsg_ma50")
    is_uptrend = None
    delta_ihsg_pct = None

    if ihsg_close and ihsg_ma50 and ihsg_ma50 > 0:
        is_uptrend = ihsg_close > ihsg_ma50
        delta_ihsg_pct = (ihsg_close - ihsg_ma50) / ihsg_ma50 * 100
        if is_uptrend:
            # makin tinggi delta, makin agresif (cap +10%)
            shift = min(0.10, max(0.02, delta_ihsg_pct / 100 * 2))
            alloc["saham_idx"] += shift
            alloc["cash"]  -= shift / 2
            alloc["emas"]  -= shift / 2
            signals.append({
                "name": "IHSG uptrend",
                "direction": "+saham",
                "weight": round(shift, 3),
                "detail": f"IHSG {delta_ihsg_pct:+.1f}% di atas MA50"
            })
        else:
            shift = min(0.12, max(0.03, abs(delta_ihsg_pct) / 100 * 2))
            alloc["saham_idx"] -= shift
            alloc["cash"]  += shift / 2
            alloc["emas"]  += shift / 2
            signals.append({
                "name": "IHSG downtrend",
                "direction": "-saham,+emas,+cash",
                "weight": round(shift, 3),
                "detail": f"IHSG {delta_ihsg_pct:+.1f}% di bawah MA50 — defensif"
            })

    # ----- SINYAL A2: Arah S&P 500 vs MA50 (US bucket) ----- #
    spx_close = (us_market_status or {}).get("spx_close")
    spx_ma50 = (us_market_status or {}).get("spx_ma50")
    if spx_close and spx_ma50 and spx_ma50 > 0:
        us_uptrend = spx_close > spx_ma50
        delta_spx_pct = (spx_close - spx_ma50) / spx_ma50 * 100
        if us_uptrend:
            shift = min(0.05, max(0.01, delta_spx_pct / 100 * 1.5))
            alloc["saham_us"] += shift
            alloc["cash"] -= shift
            signals.append({
                "name": "S&P 500 uptrend",
                "direction": "+saham_us",
                "weight": round(shift, 3),
                "detail": f"SPX {delta_spx_pct:+.1f}% di atas MA50 — geser ke US"
            })
        else:
            shift = min(0.06, max(0.01, abs(delta_spx_pct) / 100 * 1.5))
            alloc["saham_us"] -= shift
            alloc["cash"] += shift
            signals.append({
                "name": "S&P 500 downtrend",
                "direction": "-saham_us,+cash",
                "weight": round(shift, 3),
                "detail": f"SPX {delta_spx_pct:+.1f}% di bawah MA50 — defensif US"
            })

    # ----- SINYAL B: OVERSOLD_GEM banyak = peluang akumulasi ----- #
    n_oversold = sum(1 for a in (alerts_today or [])
                     if a.get("type") == "OVERSOLD_GEM")
    if n_oversold >= 8:
        shift = min(0.05, n_oversold * 0.004)
        alloc["saham_idx"] += shift
        alloc["cash"]  -= shift
        signals.append({
            "name": f"{n_oversold} OVERSOLD_GEM",
            "direction": "+saham",
            "weight": round(shift, 3),
            "detail": "Banyak saham fundamental kuat lagi oversold — akumulasi"
        })

    # ----- SINYAL C: CUT_LOSS atau urgent SELL = defensif ----- #
    n_cut_loss = sum(1 for a in (alerts_today or [])
                     if a.get("type") == "CUT_LOSS")
    n_urgent_sell = 0
    if decisions:
        n_urgent_sell = sum(1 for d in decisions.get("sell", [])
                            if d.get("urgency") == "URGENT")
    n_warning = n_cut_loss + n_urgent_sell
    if n_warning >= 1:
        shift = min(0.10, n_warning * 0.04)
        alloc["saham_idx"] -= shift
        alloc["cash"]  += shift
        signals.append({
            "name": f"{n_warning} warning di portfolio",
            "direction": "-saham,+cash",
            "weight": round(shift, 3),
            "detail": f"{n_cut_loss} cut-loss + {n_urgent_sell} urgent SELL — exit dulu"
        })

    # ----- SINYAL D: RSI emas ----- #
    gold_rsi = (gold_signal or {}).get("rsi")
    if gold_rsi is not None:
        if gold_rsi >= 70:
            shift = min(0.05, (gold_rsi - 70) / 30 * 0.05 + 0.02)
            alloc["emas"] -= shift
            alloc["cash"] += shift
            signals.append({
                "name": "Emas overbought",
                "direction": "-emas,+cash",
                "weight": round(shift, 3),
                "detail": f"RSI emas {gold_rsi:.1f} — pertimbangkan profit-take sebagian"
            })
        elif gold_rsi <= 30:
            shift = min(0.05, (30 - gold_rsi) / 30 * 0.05 + 0.02)
            alloc["emas"] += shift
            alloc["cash"] -= shift / 2
            alloc["saham_idx"] -= shift / 2
            signals.append({
                "name": "Emas oversold",
                "direction": "+emas",
                "weight": round(shift, 3),
                "detail": f"RSI emas {gold_rsi:.1f} — akumulasi safe-haven"
            })

    # ----- Normalisasi & clipping ----- #
    target = _normalize(alloc)
    # Tambah alias "saham" (= total IDX+US) untuk kompat dengan UI lama
    target["saham"] = round(target["saham_idx"] + target["saham_us"], 3)

    # ----- Hitung alokasi saat ini (4 bucket) ----- #
    total_value = (portfolio_value_rp + us_portfolio_value_rp +
                   broker_cash_rp + gold_value_rp)
    current = {"saham_idx": 0.0, "saham_us": 0.0, "emas": 0.0, "cash": 0.0, "saham": 0.0}
    if total_value > 0:
        current["saham_idx"] = portfolio_value_rp / total_value
        current["saham_us"]  = us_portfolio_value_rp / total_value
        current["cash"]      = broker_cash_rp / total_value
        current["emas"]      = gold_value_rp / total_value
        current["saham"]     = current["saham_idx"] + current["saham_us"]

    # Delta untuk 4 bucket utama (skip alias "saham")
    delta = {k: round(target[k] - current.get(k, 0.0), 3)
             for k in ("saham_idx", "saham_us", "emas", "cash")}
    delta["saham"] = round(delta["saham_idx"] + delta["saham_us"], 3)

    # ----- Verdict naratif ----- #
    if is_uptrend is True and n_warning == 0:
        verdict = "🟢 Market uptrend, portfolio sehat — boleh agresif geser ke saham"
        action = "REBALANCE" if any(abs(v) > 0.05 for v in delta.values()) else "HOLD_CURRENT"
    elif is_uptrend is False:
        verdict = "🔴 IHSG downtrend — naikkan cash & emas, tahan entry baru"
        action = "DEFENSIVE"
    elif n_warning >= 1:
        verdict = f"⚠️ Ada {n_warning} aksi exit prioritas — eksekusi cut-loss dulu sebelum buying"
        action = "DEFENSIVE"
    elif n_oversold >= 8:
        verdict = f"🟡 {n_oversold} setup oversold tersedia — peluang akumulasi bertahap"
        action = "REBALANCE"
    else:
        verdict = "⚖️ Pasar netral — pertahankan alokasi baseline, tidak perlu aksi besar"
        action = "HOLD_CURRENT"

    return {
        "target":  {k: round(v, 3) for k, v in target.items()},
        "current": {k: round(v, 3) for k, v in current.items()},
        "delta":   delta,
        "signals": signals,
        "verdict": verdict,
        "action":  action,
        "buckets": ["saham_idx", "saham_us", "emas", "cash"],
        "baseline": BASELINE.copy(),
        "constraints": {
            "min_cash": MIN_CASH, "min_saham": MIN_SAHAM, "max_saham": MAX_SAHAM,
            "min_emas": MIN_EMAS, "max_emas": MAX_EMAS
        }
    }


# ---------- Helper: hitung sinyal emas dari history harga ---------- #
def gold_rsi_from_history(history: List[Dict], period: int = 14) -> Optional[float]:
    """Hitung RSI sederhana dari list [{date, price}]. Return None jika data kurang."""
    if not history or len(history) < period + 1:
        return None
    prices = [float(h.get("price", 0)) for h in history if h.get("price")]
    if len(prices) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        chg = prices[i] - prices[i - 1]
        if chg > 0:
            gains += chg
        else:
            losses -= chg
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return round(100 - (100 / (1 + rs)), 2)
