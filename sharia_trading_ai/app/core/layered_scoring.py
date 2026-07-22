"""
Scoring rekomendasi saham syariah (framework spreadsheet).

Alur:
  Hard Gate (pass/fail) → Quality Score 0–100 → Timing Score 0–100
  → Regime Multiplier → Final Score → keputusan STRONG BUY / WATCHLIST / SKIP

Final Score = (Quality × Regime Multiplier) + Timing Bonus
  Timing Bonus = 0 saat default (contoh spreadsheet: Final ≈ Quality × Mult);
  Timing ≥ 65 = layak entry (filter terpisah untuk eligible BELI penuh).
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import SCORE, settings


def classify_regime_ma(
    ma20: Optional[float],
    ma60: Optional[float],
    *,
    defensive: bool = False,
) -> dict[str, Any]:
    """Klasifikasi regime dari MA20 vs MA60 indeks (IHSG / S&P)."""
    if ma20 is None or ma60 is None or ma60 <= 0:
        return {
            "regime": "NEUTRAL",
            "pct_ma20_vs_ma60": None,
            "extreme_downtrend": False,
            "size_mult": SCORE.REGIME_SIZE["NEUTRAL"],
            "block_new_entry": False,
            "defensive": defensive,
            "label": "Data indeks tidak cukup — anggap NEUTRAL",
        }
    pct = (ma20 - ma60) / ma60 * 100
    band = SCORE.REGIME_NEUTRAL_BAND_PCT
    extreme = pct < -SCORE.IHSG_EXTREME_DOWNTREND_PCT

    if pct > band:
        regime = "BULLISH"
    elif pct < -band:
        regime = "BEARISH"
    else:
        regime = "NEUTRAL"

    if regime == "BEARISH":
        if defensive and not extreme:
            size_mult = SCORE.REGIME_BEARISH_DEFENSIVE
            block = False
        else:
            size_mult = 0.0
            block = True
    else:
        size_mult = SCORE.REGIME_SIZE[regime]
        block = False

    return {
        "regime": regime,
        "pct_ma20_vs_ma60": round(pct, 2),
        "pct_vs_sma200": None,  # kompatibilitas UI
        "extreme_downtrend": extreme,
        "size_mult": size_mult,
        "block_new_entry": block,
        "defensive": defensive,
        "label": {
            "BULLISH": f"Bullish — MA20 > MA60 ({pct:+.1f}%)",
            "NEUTRAL": f"Netral — MA20 ≈ MA60 ({pct:+.1f}%)",
            "BEARISH": (
                f"Bearish ekstrem — MA20 < MA60 by >{SCORE.IHSG_EXTREME_DOWNTREND_PCT:.0f}% ({pct:+.1f}%)"
                if extreme else
                f"Bearish — MA20 < MA60 ({pct:+.1f}%)"
                + (" · defensif ×0.5" if defensive and not extreme else "")
            ),
        }[regime],
    }


def classify_regime(close: Optional[float], sma200: Optional[float],
                    *, defensive: bool = False) -> dict[str, Any]:
    """Fallback legacy: harga indeks vs SMA200 (jika MA60 tidak tersedia)."""
    if close is None or sma200 is None or sma200 <= 0:
        return classify_regime_ma(None, None, defensive=defensive)
    pct = (close - sma200) / sma200 * 100
    band = SCORE.REGIME_SMA200_BAND_PCT
    extreme = pct < -SCORE.IHSG_EXTREME_DOWNTREND_PCT
    if pct > 0:
        regime = "BULLISH"
    elif pct >= -band:
        regime = "NEUTRAL"
    else:
        regime = "BEARISH"

    if regime == "BEARISH":
        if defensive and not extreme:
            size_mult = SCORE.REGIME_BEARISH_DEFENSIVE
            block = False
        else:
            size_mult = 0.0
            block = True
    else:
        size_mult = SCORE.REGIME_SIZE[regime]
        block = False

    return {
        "regime": regime,
        "pct_vs_sma200": round(pct, 2),
        "pct_ma20_vs_ma60": None,
        "extreme_downtrend": extreme,
        "size_mult": size_mult,
        "block_new_entry": block,
        "defensive": defensive,
        "label": {
            "BULLISH": f"Risk-on — harga di atas SMA200 ({pct:+.1f}%)",
            "NEUTRAL": f"Netral — dekat SMA200 ({pct:+.1f}%)",
            "BEARISH": f"Risk-off — harga di bawah SMA200 ({pct:+.1f}%)",
        }[regime],
    }


def is_defensive_stock(fund: Optional[dict], tech: Optional[dict] = None) -> bool:
    """Saham defensif: DY tinggi / ROE kuat + PER wajar / volatilitas rendah."""
    fund = fund or {}
    raw = fund.get("raw") or {}
    dy = raw.get("dividend_yield")
    roe = raw.get("roe")
    per = raw.get("per")
    magic = float(fund.get("magic_score") or 0)
    atr_pct = ((tech or {}).get("atr") or {}).get("pct")

    if dy is not None and float(dy) >= 5.0:
        return True
    if roe is not None and float(roe) >= 15 and per is not None and float(per) <= 20:
        return True
    if magic >= 4 and atr_pct is not None and float(atr_pct) < 3.0:
        return True
    return False


def market_regime_for(ticker: Optional[str] = None,
                      *, defensive: bool = False) -> dict[str, Any]:
    """Regime untuk ticker: IDX → IHSG, US → S&P 500 (MA20 vs MA60)."""
    try:
        from app.data import provider
        import math
        idx_df = provider.get_index_history(ticker, period="5y")
        if idx_df is None or idx_df.empty or len(idx_df) < 60:
            return classify_regime_ma(None, None, defensive=defensive)
        close_s = idx_df["Close"]
        ma20 = float(close_s.rolling(20).mean().iloc[-1])
        ma60 = float(close_s.rolling(60).mean().iloc[-1])
        if math.isnan(ma20) or math.isnan(ma60):
            # fallback SMA200
            if len(idx_df) >= 200:
                close = float(close_s.iloc[-1])
                sma200 = float(close_s.rolling(200).mean().iloc[-1])
                if not (math.isnan(close) or math.isnan(sma200)):
                    out = classify_regime(close, sma200, defensive=defensive)
                    out["index"] = "^GSPC" if provider.is_us_ticker(ticker or "") else "^JKSE"
                    return out
            return classify_regime_ma(None, None, defensive=defensive)
        out = classify_regime_ma(ma20, ma60, defensive=defensive)
        out["index"] = "^GSPC" if provider.is_us_ticker(ticker or "") else "^JKSE"
        out["ma20"] = round(ma20, 2)
        out["ma60"] = round(ma60, 2)
        return out
    except Exception:  # noqa: BLE001
        return classify_regime_ma(None, None, defensive=defensive)


# --------------------------------------------------------------------------- #
#  Quality components (skor 0–100 × bobot spreadsheet)                         #
# --------------------------------------------------------------------------- #

def _score_fundamental_100(fund: dict, cslim: dict) -> float:
    """=IF(PER<15,80,IF(PER<25,50,30)) + ROE>15 bonus +10."""
    raw = (fund or {}).get("raw") or {}
    per = raw.get("per")
    roe = raw.get("roe")

    if per is not None:
        try:
            p = float(per)
            if p < 15:
                base = 80.0
            elif p < 25:
                base = 50.0
            else:
                base = 30.0
        except (TypeError, ValueError):
            base = None
    else:
        base = None

    if base is None:
        # fallback Magic + CAN SLIM
        magic = float((fund or {}).get("magic_score") or 0)
        cs = float((cslim or {}).get("canslim_score") or 0)
        base = (magic / 6.0) * 55 + (cs / 7.0) * 45

    if roe is not None:
        try:
            if float(roe) > 15:
                base = min(100.0, base + 10)
        except (TypeError, ValueError):
            pass
    return max(0.0, min(100.0, float(base)))


def _score_technical_100(tech: dict) -> float:
    """=IF(MA20>MA60,80,50); downtrend eksplisit → 30 (tabel 0–49)."""
    if not tech or not tech.get("ok"):
        return 50.0
    t = tech.get("trend_ma20_60") or tech.get("trend")
    sma = tech.get("sma") or {}
    s20, s60 = sma.get("sma20"), sma.get("sma60")
    if s20 is not None and s60 is not None:
        if s20 > s60:
            return 80.0
        if s20 < s60:
            return 30.0
        return 50.0
    if t == "UPTREND":
        return 80.0
    if t == "DOWNTREND":
        return 30.0
    return 50.0


def _score_bandar_100(bandar: Optional[dict], tech: Optional[dict] = None) -> float:
    """Akumulasi volume + sentimen bandar."""
    score = 50.0
    vol = (tech or {}).get("volume") or {}
    if vol.get("spike") or vol.get("spike_2x"):
        score = 80.0
    if not bandar:
        return score
    raw = bandar.get("score")
    if isinstance(raw, (int, float)):
        return max(0.0, min(100.0, float(raw)))
    sent = (bandar.get("sentiment") or "").upper()
    if "AKUMULASI BESAR" in sent:
        return 95.0
    if "AKUMULASI" in sent:
        return 80.0
    if "DISTRIBUSI BESAR" in sent:
        return 15.0
    if "DISTRIBUSI" in sent:
        return 30.0
    return score


def _score_liquidity_100(tech: dict) -> float:
    """Spread <0.5% = 90, <1% = 70, <2% = 50."""
    spread = (tech or {}).get("spread_pct")
    if spread is not None:
        try:
            s = float(spread)
            if s < 0.5:
                return 90.0
            if s < 1.0:
                return 70.0
            if s <= 2.0:
                return 50.0
            return 25.0
        except (TypeError, ValueError):
            pass
    risk = (tech or {}).get("liquidity_risk") or "Sedang"
    if risk == "Rendah":
        return 90.0
    if risk == "Sedang":
        return 55.0
    return 20.0


def _score_ihsg_100(regime_info: dict) -> float:
    """IHSG uptrend=80, sideways=60, downtrend=30 (tabel Quality)."""
    r = regime_info.get("regime") or "NEUTRAL"
    return {"BULLISH": 80.0, "NEUTRAL": 60.0, "BEARISH": 30.0}.get(r, 60.0)


def _score_risk_100(tech: dict, j7: Optional[dict] = None) -> float:
    """=IF(SL_dist>2*spread,80,40)."""
    price = (tech or {}).get("price")
    atr = (tech or {}).get("atr") or {}
    sl = atr.get("sl_2atr")
    spread_pct = (tech or {}).get("spread_pct")

    if price and sl and spread_pct is not None and float(spread_pct) > 0:
        try:
            sl_dist_pct = abs(float(price) - float(sl)) / float(price) * 100
            base = 80.0 if sl_dist_pct > 2.0 * float(spread_pct) else 40.0
        except (TypeError, ValueError, ZeroDivisionError):
            base = 40.0
    elif atr.get("sl_2atr") and atr.get("tp_4atr"):
        base = 80.0
    else:
        base = 40.0

    if j7 and j7.get("ok") and (j7.get("score") or 0) >= 2:
        base = min(100.0, base + 5)
    return max(0.0, min(100.0, base))


def compute_timing_score(tech: dict, osignal: Optional[dict] = None) -> dict[str, Any]:
    """Timing Score 0–100 terpisah dari Quality."""
    if not tech or not tech.get("ok"):
        return {"timing_score": 40, "layak_entry": False, "factors": ["data teknikal kurang"]}

    factors: list[str] = []
    score = 55.0  # baseline

    rsi_v = tech.get("rsi")
    if rsi_v is None and osignal:
        rsi_v = osignal.get("rsi")
    if rsi_v is not None:
        try:
            r = float(rsi_v)
            if 30 <= r <= 50:
                score = 90.0
                factors.append(f"RSI {r:.0f} zona oversold-reversal")
            elif 50 < r <= 70:
                score = 65.0
                factors.append(f"RSI {r:.0f} trend lanjutan")
            elif r < 30:
                score = 70.0
                factors.append(f"RSI {r:.0f} oversold dalam")
            else:
                score = 40.0
                factors.append(f"RSI {r:.0f} overbought")
        except (TypeError, ValueError):
            pass

    vol = tech.get("volume") or {}
    if vol.get("spike_2x") or (
        vol.get("now") and vol.get("avg20") and float(vol["now"]) > 2.0 * float(vol["avg20"])
    ):
        score = min(100.0, score + 20)
        factors.append("volume spike >2× rata-rata (+20)")

    gap = tech.get("gap_pct")
    if gap is not None and abs(float(gap)) >= SCORE.TIMING_GAP_SIGNIFICANT_PCT:
        score = max(0.0, score - 30)
        factors.append(f"gap {float(gap):+.1f}% signifikan (−30)")

    # Support test dekat MA20/MA60
    price = tech.get("price")
    sma = tech.get("sma") or {}
    near = False
    if price:
        for key in ("sma20", "sma60", "sma50"):
            mv = sma.get(key)
            if mv and float(mv) > 0:
                dist = abs(float(price) - float(mv)) / float(mv) * 100
                if dist <= SCORE.TIMING_SUPPORT_NEAR_PCT:
                    near = True
                    break
    if not near and tech.get("support") and price:
        try:
            dist = abs(float(price) - float(tech["support"])) / float(price) * 100
            near = dist <= SCORE.TIMING_SUPPORT_NEAR_PCT
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    if near:
        score = min(100.0, score + 15)
        factors.append("dekat support / MA (+15)")

    # Sinyal O'Neill / entry soft boost
    t_sig = (osignal or {}).get("signal") or ""
    if t_sig == "BUY":
        score = min(100.0, score + 5)
    elif t_sig == "SELL":
        score = max(0.0, score - 10)

    timing = int(round(max(0.0, min(100.0, score))))
    return {
        "timing_score": timing,
        "layak_entry": timing >= SCORE.TIMING_ENTRY_MIN,
        "factors": factors,
    }


def decide_final(final_score: float) -> str:
    if final_score >= SCORE.FINAL_STRONG_BUY:
        return "STRONG BUY"
    if final_score >= SCORE.FINAL_WATCHLIST:
        return "WATCHLIST"
    return "SKIP"


def evaluate_hard_gates(
    sharia: dict,
    tech: dict,
    regime_info: dict,
    *,
    enforce_regime_entry_block: bool = True,
) -> dict[str, Any]:
    """Hard gates. Satu FAIL → STOP (skip saham)."""
    gates: list[dict[str, Any]] = []

    # 1. DES/ISSI
    syariah_ok = bool(sharia.get("compliant"))
    des_status = sharia.get("des_status") or ""
    if syariah_ok and des_status == "outside_curated":
        des_detail = "DSN-MUI OK · di luar universe funnel — verifikasi DES mandiri"
    elif syariah_ok:
        des_detail = "Lolos DES/ISSI"
    else:
        des_detail = "Non-syariah — ditolak"
    gates.append({
        "id": "des_issi",
        "nama": "DES/ISSI (Syariah)",
        "passed": syariah_ok,
        "detail": des_detail,
    })

    # 2. Likuiditas: volume IDR median 5d ≥ Rp5M (+ bukan illiquid lembar).
    #    Bid-ask ≤2% dari spreadsheet hanya dipakai bila ada spread riil;
    #    daily HL range / ATR% = proksi Quality, BUKAN hard-fail (hindari false AVOID).
    if tech and tech.get("ok"):
        vol_idr = tech.get("vol_idr_median_5d")
        liq_risk = tech.get("liquidity_risk")
        daily_range = tech.get("daily_range_pct")
        spread = tech.get("spread_pct")  # ATR% / proksi
        parts = []
        ok_vol = True
        if vol_idr is not None:
            ok_vol = float(vol_idr) >= SCORE.VOL_IDR_MEDIAN_5D_MIN
            parts.append(
                f"vol median 5d Rp{float(vol_idr):,.0f} "
                f"{'≥' if ok_vol else '<'} Rp{SCORE.VOL_IDR_MEDIAN_5D_MIN:,.0f}"
            )
        else:
            ok_vol = liq_risk != SCORE.LIQUIDITY_FAIL
            parts.append(f"risiko likuiditas: {liq_risk or '—'} (fallback volume)")

        ok_not_illiquid = liq_risk != SCORE.LIQUIDITY_FAIL
        if liq_risk:
            parts.append(f"volume-lembar: {liq_risk}")

        # Hanya gagalkan range ekstrem bila volume juga tipis (gorengan)
        ok_range = True
        if (
            daily_range is not None
            and float(daily_range) > SCORE.DAILY_RANGE_EXTREME_PCT
            and not ok_not_illiquid
        ):
            ok_range = False
            parts.append(
                f"range harian {float(daily_range):.1f}% ekstrem + illiquid"
            )
        elif daily_range is not None:
            parts.append(f"range harian {float(daily_range):.2f}% (bukan bid-ask)")
        if spread is not None:
            parts.append(f"ATR/proksi {float(spread):.2f}%")

        liq_ok = ok_vol and ok_not_illiquid and ok_range
        gates.append({
            "id": "likuiditas",
            "nama": "Likuiditas minimum",
            "passed": liq_ok,
            "detail": " · ".join(parts) if parts else "Data likuiditas kosong",
        })
    else:
        gates.append({
            "id": "likuiditas",
            "nama": "Likuiditas minimum",
            "passed": True,
            "detail": "Data teknikal tidak cukup — gate likuiditas dilewati (skor akan rendah)",
        })

    # 3. IHSG: bukan downtrend ekstrem (MA20 < MA60 by >5%)
    extreme = bool(regime_info.get("extreme_downtrend"))
    if enforce_regime_entry_block:
        ihsg_ok = not extreme
    else:
        ihsg_ok = True
    gates.append({
        "id": "regime",
        "nama": "IHSG Regime (bukan ekstrem)",
        "passed": ihsg_ok,
        "detail": (
            "⛔ Downtrend ekstrem IHSG (MA20 < MA60 by >5%)"
            if extreme else
            (regime_info.get("label") or regime_info.get("regime") or "—")
        ),
    })

    failed = [g for g in gates if not g["passed"]]
    return {
        "passed": len(failed) == 0,
        "gates": gates,
        "failed": [g["id"] for g in failed],
        "failed_detail": [g["detail"] for g in failed],
    }


def compute_layered_score(
    *,
    sharia: dict,
    fund: dict,
    cslim: dict,
    tech: dict,
    bandar: Optional[dict] = None,
    j7: Optional[dict] = None,
    osignal: Optional[dict] = None,
    ticker: Optional[str] = None,
    regime_info: Optional[dict] = None,
) -> dict[str, Any]:
    """Hard gate + Quality + Timing + Regime Multiplier + Final Score."""
    defensive = is_defensive_stock(fund or {}, tech or {})
    if regime_info is None:
        regime_info = market_regime_for(ticker, defensive=defensive)
    else:
        # pastikan size_mult mempertimbangkan defensif jika bearish
        if regime_info.get("regime") == "BEARISH" and defensive and not regime_info.get("extreme_downtrend"):
            regime_info = {**regime_info, "defensive": True,
                           "size_mult": SCORE.REGIME_BEARISH_DEFENSIVE,
                           "block_new_entry": False}

    gates = evaluate_hard_gates(sharia, tech or {}, regime_info)

    # Quality components 0–100
    q100 = {
        "fundamental": round(_score_fundamental_100(fund or {}, cslim or {}), 1),
        "teknikal": round(_score_technical_100(tech or {}), 1),
        "bandarmologi": round(_score_bandar_100(bandar, tech), 1),
        "likuiditas": round(_score_liquidity_100(tech or {}), 1),
        "ihsg": round(_score_ihsg_100(regime_info), 1),
        "risk": round(_score_risk_100(tech or {}, j7), 1),
    }
    weights = {
        "fundamental": SCORE.W_FUNDAMENTAL,
        "teknikal": SCORE.W_TECHNICAL,
        "bandarmologi": SCORE.W_BANDAR,
        "likuiditas": SCORE.W_LIQUIDITY,
        "ihsg": SCORE.W_IHSG,
        "risk": SCORE.W_RISK,
    }
    quality = sum(q100[k] * weights[k] for k in q100)
    quality = round(quality, 1)

    timing_info = compute_timing_score(tech or {}, osignal)
    timing = timing_info["timing_score"]

    mult = float(regime_info.get("size_mult", 1.0))
    # Timing Bonus: contoh spreadsheet Final = Quality×Mult (bonus 0).
    # Timing tetap dipakai sebagai filter layak entry (≥65), bukan penambah Final.
    timing_bonus = 0.0

    if not gates["passed"]:
        final_score = 0.0
        keputusan = "SKIP"
    else:
        final_score = round(quality * mult + timing_bonus, 1)
        keputusan = decide_final(final_score)

    # Eligible BELI penuh: lolos gate, mult>0, keputusan bukan SKIP,
    # dan timing layak (atau WATCHLIST tetap boleh dipantau)
    block = bool(regime_info.get("block_new_entry")) or mult <= 0
    eligible = (
        gates["passed"]
        and not block
        and keputusan == "STRONG BUY"
        and timing_info["layak_entry"]
    )

    skor = int(round(max(0.0, min(105.0, final_score if gates["passed"] else 0.0))))

    components = {}
    for k in q100:
        # nilai 0–1 untuk kompatibilitas UI progress bar
        nilai = q100[k] / 100.0
        components[k] = {
            "nilai": round(nilai, 4),
            "skor_100": q100[k],
            "bobot": weights[k],
            "kontribusi": round(q100[k] * weights[k], 1),
        }

    return {
        "model": "layered",
        "skor": skor,
        "quality_score": quality,
        "timing_score": timing,
        "timing_layak_entry": timing_info["layak_entry"],
        "timing_factors": timing_info.get("factors") or [],
        "timing_bonus": round(timing_bonus, 2),
        "final_score": final_score,
        "keputusan": keputusan,
        "components": components,
        "gates": gates,
        "regime": regime_info,
        "size_mult": mult,
        "block_new_entry": block,
        "eligible_for_buy": eligible,
        "defensive": defensive,
    }


def legacy_score(fund: dict, cslim: dict, tech: dict, j7: Optional[dict],
                 osignal: Optional[dict]) -> int:
    """Skor lama (Magic 35% + CAN SLIM 35% + tech 15% + Jalur7 15%)."""
    magic = float(fund.get("magic_score") or 0)
    cs = float(cslim.get("canslim_score") or 0)
    t_signal = (osignal or {}).get("signal") or (
        "BUY" if (tech.get("ok") and "BULLISH" in tech.get("bias", "")) else "HOLD"
    )
    tech_pos = 1 if t_signal == "BUY" else 0
    j7_score = j7["score"] if (j7 and j7.get("ok")) else None
    j7_norm = (j7_score / 4) if j7_score is not None else 0
    return round((magic / 6 * 0.35 + cs / 7 * 0.35 + tech_pos * 0.15 + j7_norm * 0.15) * 100)


def use_layered() -> bool:
    return (settings.scoring_model or "layered").lower() != "legacy"
