"""
Rotation Advisor — Reserve Asset Pool (Emas ↔ Saham)
=====================================================
Layer 2 dari arsitektur 3-layer. Emas & Dinar diperlakukan sebagai
**reserve asset pool** — bukan trading spekulatif — dengan dynamic rotation
ke saham syariah saat kondisi mendukung.

Trigger Rotation
================

EMAS → SAHAM (Risk-On Rotation)
  - Global factor status = RISK_ON
  - Ada saham trading_score ≥ TS_ENTRY (default 70)
  - Emas current % > target % (overweight relatif ke rebalancer target)
  - IHSG di atas MA50 (konfirmasi domestik)

SAHAM → EMAS (Risk-Off Parking)
  - Global factor status = RISK_OFF
  - Tidak ada saham dengan trading_score ≥ TS_WATCHLIST (50)
  - Cash idle besar (> 15% total aset)
  - Emas current % < target %

HOLD ALL (Neutral)
  - Status NEUTRAL atau kondisi rotation tidak terpenuhi

Mode: RECOMMEND-ONLY (sesuai konfirmasi user)
  Output adalah suggestion list yang user eksekusi manual di Pegadaian /
  broker. Tidak ada auto-trade.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# Threshold untuk trigger
MIN_TARGET_GAP_PCT = 0.02   # gap target-current minimum 2% baru rotate
MIN_ROTATION_RP    = 500_000  # nominal minimum supaya tidak rotasi receh
MAX_ROTATION_PCT_PER_DAY = 0.15  # max 15% bucket value boleh dirotasi per hari (anti over-trading)


@dataclass
class RotationSuggestion:
    """Satu rekomendasi rotation."""
    action: str                   # "ROTATE_GOLD_TO_STOCK" | "ROTATE_STOCK_TO_GOLD" | "ACCUMULATE_GOLD" | "ACCUMULATE_CASH"
    direction: str                # "emas → saham" | "saham → emas" | dst
    amount_rp: float              # nominal yang disarankan
    from_asset: str               # "emas" | "saham_idx" | "cash"
    to_asset: str                 # idem
    target_ticker: Optional[str] = None   # kalau ada saham specific
    rationale: str = ""
    confidence: str = "MEDIUM"     # HIGH / MEDIUM / LOW
    next_step: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def _to_dict(s: RotationSuggestion) -> Dict[str, Any]:
    return asdict(s)


def generate_rotation_suggestions(
    global_factor: Dict[str, Any],
    allocation: Dict[str, Any],
    top_stocks_with_score: List[Dict[str, Any]],
    market_status: Optional[Dict[str, Any]] = None,
    ts_entry_threshold: float = 70.0,
    ts_watchlist_threshold: float = 50.0,
) -> Dict[str, Any]:
    """
    Hasilkan list rotation suggestion berdasar 3-layer signal.

    Args:
        global_factor: output compute_global_factor()
        allocation:    output compute_allocation() → ambil .amounts.gap_rp/current_rp/target_rp
        top_stocks_with_score: list saham + trading_score (ranked desc)
        market_status: {ihsg_close, ihsg_ma50} — konfirmasi domestik
        ts_entry_threshold:    score di atas mana saham layak entry agresif
        ts_watchlist_threshold: score di bawah mana semua saham dianggap lemah

    Returns:
        {
          "trigger_status": "ROTATE_GOLD_TO_STOCK" | "ROTATE_STOCK_TO_GOLD" |
                             "ACCUMULATE_CASH" | "HOLD_ALL",
          "global_status":  str (RISK_ON/RISK_OFF/NEUTRAL),
          "narrative":      str,
          "suggestions":    [list of RotationSuggestion dicts]
        }
    """
    suggestions: List[RotationSuggestion] = []

    g_status = (global_factor or {}).get("status", "NEUTRAL")
    g_score = float((global_factor or {}).get("score") or 50)
    influence_mult = float((global_factor or {}).get("influence_multiplier") or 1.0)

    # Amounts breakdown dari allocation
    amounts = (allocation or {}).get("amounts") or {}
    current_rp = amounts.get("current_rp") or {}
    target_rp = amounts.get("target_rp") or {}
    gap_rp = amounts.get("gap_rp") or {}
    total_asset = float(amounts.get("total_asset_rp") or 0)

    emas_current = float(current_rp.get("emas") or 0)
    emas_target  = float(target_rp.get("emas") or 0)
    emas_gap     = float(gap_rp.get("emas") or 0)           # +bid = perlu beli emas
    saham_gap    = float(gap_rp.get("saham") or 0)
    cash_current = float(current_rp.get("cash") or 0)
    cash_target  = float(target_rp.get("cash") or 0)

    # Konfirmasi IHSG (domestik)
    ihsg_uptrend = None
    if market_status and market_status.get("ihsg_close") and market_status.get("ihsg_ma50"):
        ihsg_uptrend = market_status["ihsg_close"] > market_status["ihsg_ma50"]

    # Saham score tertinggi
    top_stock = None
    if top_stocks_with_score:
        scored = [s for s in top_stocks_with_score
                  if (s.get("trading_score") or {}).get("score") is not None]
        if scored:
            scored.sort(
                key=lambda s: float(s["trading_score"]["score"]),
                reverse=True
            )
            top_stock = scored[0]

    top_ts_score = 0.0
    top_ticker = None
    if top_stock:
        top_ts_score = float(top_stock["trading_score"]["score"])
        top_ticker = top_stock.get("ticker")

    # ----- TRIGGER 1: ROTATE EMAS → SAHAM (Risk-On Rotation) -----
    trigger = "HOLD_ALL"
    if (
        g_status == "RISK_ON"
        and top_ts_score >= ts_entry_threshold
        and emas_current > emas_target * (1 + MIN_TARGET_GAP_PCT)
        and (ihsg_uptrend is None or ihsg_uptrend)
        and saham_gap > 0
    ):
        # Berapa yang dirotasi: min(emas_overweight_rp, saham_gap_rp, max_15%_emas)
        emas_overweight_rp = emas_current - emas_target
        max_rotate_rp = emas_current * MAX_ROTATION_PCT_PER_DAY
        amount = min(emas_overweight_rp, saham_gap, max_rotate_rp)
        if amount >= MIN_ROTATION_RP:
            trigger = "ROTATE_GOLD_TO_STOCK"
            suggestions.append(RotationSuggestion(
                action="ROTATE_GOLD_TO_STOCK",
                direction="emas → saham",
                amount_rp=round(amount, 0),
                from_asset="emas",
                to_asset="saham_idx",
                target_ticker=top_ticker,
                confidence="HIGH" if g_score >= 75 and top_ts_score >= 80 else "MEDIUM",
                rationale=(
                    f"Global RISK_ON (score {g_score:.0f}/100) + "
                    f"{top_ticker} trading score {top_ts_score:.0f}≥{ts_entry_threshold:.0f} + "
                    f"emas overweight Rp{emas_overweight_rp:,.0f}"
                ),
                next_step=(
                    f"Jual ~Rp{amount:,.0f} emas di Pegadaian → "
                    f"alokasikan beli {top_ticker} sesuai daily_buy_plan."
                ),
                meta={
                    "global_score": g_score,
                    "top_stock_score": top_ts_score,
                    "emas_overweight_rp": round(emas_overweight_rp, 0),
                    "saham_gap_rp": round(saham_gap, 0),
                }
            ))

    # ----- TRIGGER 2: ROTATE SAHAM/CASH → EMAS (Risk-Off Parking) -----
    elif (
        g_status == "RISK_OFF"
        and top_ts_score < ts_watchlist_threshold
        and emas_current < emas_target * (1 - MIN_TARGET_GAP_PCT)
        and emas_gap > 0
    ):
        # Sumber dana: cash idle dulu, kalau kurang baru tarik dari saham yang lemah
        cash_idle = max(0.0, cash_current - cash_target)
        amount_from_cash = min(cash_idle, emas_gap)
        max_rotate_rp = emas_target * MAX_ROTATION_PCT_PER_DAY
        amount_from_cash = min(amount_from_cash, max_rotate_rp)
        if amount_from_cash >= MIN_ROTATION_RP:
            trigger = "ROTATE_STOCK_TO_GOLD"
            suggestions.append(RotationSuggestion(
                action="ACCUMULATE_GOLD",
                direction="cash → emas",
                amount_rp=round(amount_from_cash, 0),
                from_asset="cash",
                to_asset="emas",
                confidence="MEDIUM",
                rationale=(
                    f"Global RISK_OFF (score {g_score:.0f}/100) + "
                    f"no saham score ≥ {ts_watchlist_threshold:.0f} + "
                    f"emas underweight Rp{abs(emas_target - emas_current):,.0f}"
                ),
                next_step=(
                    f"Topup ~Rp{amount_from_cash:,.0f} cash → beli emas di "
                    f"Pegadaian (akumulasi safe-haven)."
                ),
                meta={
                    "global_score": g_score,
                    "cash_idle_rp": round(cash_idle, 0),
                    "emas_underweight_rp": round(emas_target - emas_current, 0),
                }
            ))

    # ----- TRIGGER 3: ACCUMULATE CASH (Defensif total) -----
    elif (
        g_status == "RISK_OFF"
        and top_ts_score < ts_watchlist_threshold
        and cash_current < cash_target * (1 - MIN_TARGET_GAP_PCT)
    ):
        trigger = "ACCUMULATE_CASH"
        cash_gap = cash_target - cash_current
        # Saran: tahan entry baru, biarkan dividen / SELL menumpuk di cash
        suggestions.append(RotationSuggestion(
            action="ACCUMULATE_CASH",
            direction="hold cash",
            amount_rp=round(cash_gap, 0),
            from_asset="-",
            to_asset="cash",
            confidence="HIGH",
            rationale=(
                f"Global RISK_OFF (score {g_score:.0f}/100) + saham score lemah "
                f"+ cash underweight Rp{cash_gap:,.0f}"
            ),
            next_step=(
                "Tahan semua entry baru, akumulasi cash dari dividen / hasil SELL "
                "untuk amunisi rotasi saat market balik."
            ),
        ))

    # ----- NARRATIVE -----
    if trigger == "ROTATE_GOLD_TO_STOCK":
        narrative = (
            f"🔄 ROTATE EMAS → SAHAM: kondisi global mendukung agresif, "
            f"manfaatkan emas overweight untuk akumulasi {top_ticker} (TS {top_ts_score:.0f})."
        )
    elif trigger == "ROTATE_STOCK_TO_GOLD":
        narrative = (
            f"🛡️ PARKIR DI EMAS: global risk-off + saham lemah; pindahkan cash idle "
            f"ke emas sebagai safe-haven."
        )
    elif trigger == "ACCUMULATE_CASH":
        narrative = (
            f"💰 AKUMULASI CASH: bertahan dulu sampai kondisi global membaik. "
            f"Hindari entry baru, biarkan cash tumbuh."
        )
    else:
        narrative = (
            f"⚖️ HOLD ALL POSITIONS: kondisi global {g_status} (score {g_score:.0f}/100); "
            f"alokasi current sudah dekat target. Tidak ada rotation aktif yang diperlukan."
        )

    return {
        "trigger_status": trigger,
        "global_status":  g_status,
        "global_score":   g_score,
        "narrative":      narrative,
        "suggestions":    [_to_dict(s) for s in suggestions],
        "params": {
            "ts_entry_threshold":    ts_entry_threshold,
            "ts_watchlist_threshold": ts_watchlist_threshold,
            "min_rotation_rp":        MIN_ROTATION_RP,
            "max_rotation_pct_per_day": MAX_ROTATION_PCT_PER_DAY,
        }
    }
