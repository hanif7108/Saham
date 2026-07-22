"""Unit test scoring rekomendasi (gate / quality / timing / final) — tanpa jaringan."""

from app.config import SCORE
from app.core import layered_scoring as ls


def _bull():
    return ls.classify_regime_ma(1100, 1000)  # +10%


def _neutral():
    return ls.classify_regime_ma(1005, 1000)  # +0.5% dalam band 1%


def _bear():
    return ls.classify_regime_ma(900, 1000)  # -10%


def _extreme():
    return ls.classify_regime_ma(940, 1000)  # -6% ekstrem


def _liq_ok_tech(**extra):
    base = {
        "ok": True,
        "liquidity_risk": "Rendah",
        "spread_pct": 0.4,
        "vol_idr_median_5d": 50_000_000,
        "trend": "UPTREND",
        "trend_ma20_60": "UPTREND",
        "price": 1000,
        "rsi": 42,
        "sma": {"sma20": 1010, "sma60": 990, "sma50": 1000},
        "volume": {"now": 3_000_000, "avg20": 1_000_000, "spike": True, "spike_2x": True},
        "atr": {"sl_2atr": 960, "tp_4atr": 1080, "pct": 2.0},
        "support": 980,
        "gap_pct": 0.3,
    }
    base.update(extra)
    return base


def test_classify_regime_ma_bullish():
    r = _bull()
    assert r["regime"] == "BULLISH"
    assert r["size_mult"] == 1.0
    assert r["block_new_entry"] is False
    assert r["extreme_downtrend"] is False


def test_classify_regime_ma_neutral():
    r = _neutral()
    assert r["regime"] == "NEUTRAL"
    assert r["size_mult"] == 0.8
    assert r["block_new_entry"] is False


def test_classify_regime_ma_bearish():
    r = _bear()
    assert r["regime"] == "BEARISH"
    assert r["size_mult"] == 0.0
    assert r["block_new_entry"] is True
    assert r["extreme_downtrend"] is True


def test_classify_regime_bearish_defensive():
    # -3% bearish tapi tidak ekstrem → defensif boleh ×0.5
    r = ls.classify_regime_ma(970, 1000, defensive=True)
    assert r["regime"] == "BEARISH"
    assert r["extreme_downtrend"] is False
    assert r["size_mult"] == 0.5
    assert r["block_new_entry"] is False


def test_classify_regime_legacy_sma200():
    r = ls.classify_regime(1100, 1000)
    assert r["regime"] == "BULLISH"
    assert r["size_mult"] == 1.0


def test_weights_match_spreadsheet():
    """=(Fund*0.3)+(Tek*0.2)+(Bandar*0.15)+(Liq*0.15)+(IHSG*0.15)+(Risk*0.1)"""
    assert SCORE.W_FUNDAMENTAL == 0.30
    assert SCORE.W_TECHNICAL == 0.20
    assert SCORE.W_BANDAR == 0.15
    assert SCORE.W_LIQUIDITY == 0.15
    assert SCORE.W_IHSG == 0.15
    assert SCORE.W_RISK == 0.10
    total = (
        SCORE.W_FUNDAMENTAL + SCORE.W_TECHNICAL + SCORE.W_BANDAR
        + SCORE.W_LIQUIDITY + SCORE.W_IHSG + SCORE.W_RISK
    )
    assert abs(total - 1.05) < 1e-9


def test_hard_gates_fail_non_sharia():
    gates = ls.evaluate_hard_gates(
        {"compliant": False},
        _liq_ok_tech(),
        _bull(),
    )
    assert gates["passed"] is False
    assert "des_issi" in gates["failed"]


def test_hard_gates_high_atr_spread_does_not_fail_if_volume_ok():
    """ATR/daily range >2% bukan hard-fail — TINS-like liquid names."""
    gates = ls.evaluate_hard_gates(
        {"compliant": True},
        _liq_ok_tech(spread_pct=3.5, daily_range_pct=2.8),
        _bull(),
    )
    assert gates["passed"] is True
    assert "likuiditas" not in gates["failed"]


def test_hard_gates_fail_low_volume_idr():
    gates = ls.evaluate_hard_gates(
        {"compliant": True},
        _liq_ok_tech(vol_idr_median_5d=1_000_000),
        _bull(),
    )
    assert gates["passed"] is False
    assert "likuiditas" in gates["failed"]


def test_hard_gates_fail_extreme_ihsg():
    gates = ls.evaluate_hard_gates(
        {"compliant": True},
        _liq_ok_tech(),
        _extreme(),
    )
    assert gates["passed"] is False
    assert "regime" in gates["failed"]


def test_hard_gates_pass_bullish():
    gates = ls.evaluate_hard_gates(
        {"compliant": True},
        _liq_ok_tech(),
        _bull(),
    )
    assert gates["passed"] is True
    assert gates["failed"] == []


def test_timing_oversold_reversal():
    t = ls.compute_timing_score(_liq_ok_tech(rsi=40, gap_pct=0.2))
    assert t["timing_score"] >= 65
    assert t["layak_entry"] is True


def test_timing_gap_penalty():
    t = ls.compute_timing_score(_liq_ok_tech(rsi=45, gap_pct=3.5, volume={"now": 1, "avg20": 1}))
    # base ~90 lalu -30 gap
    assert t["timing_score"] < 80


def test_compute_layered_score_structure():
    out = ls.compute_layered_score(
        sharia={"compliant": True},
        fund={"magic_score": 5, "raw": {"per": 12, "roe": 18}},
        cslim={"canslim_score": 5},
        tech=_liq_ok_tech(),
        bandar={"score": 80, "sentiment": "AKUMULASI"},
        j7={"ok": True, "score": 3},
        osignal={"signal": "BUY", "rsi": 42},
        regime_info=_bull(),
    )
    assert out["model"] == "layered"
    assert 0 <= out["skor"] <= 105
    assert out["keputusan"] in ("STRONG BUY", "WATCHLIST", "SKIP")
    assert out["final_score"] is not None
    assert out["quality_score"] is not None
    assert out["timing_score"] is not None
    assert "fundamental" in out["components"]
    assert "ihsg" in out["components"]
    assert out["components"]["fundamental"]["bobot"] == SCORE.W_FUNDAMENTAL
    assert abs(out["final_score"] - out["quality_score"] * out["size_mult"] - out["timing_bonus"]) < 0.2


def test_compute_layered_strong_buy_path():
    out = ls.compute_layered_score(
        sharia={"compliant": True},
        fund={"magic_score": 6, "raw": {"per": 10, "roe": 20}},
        cslim={"canslim_score": 6},
        tech=_liq_ok_tech(),
        bandar={"score": 90, "sentiment": "AKUMULASI BESAR"},
        j7={"ok": True, "score": 3},
        osignal={"signal": "BUY", "rsi": 40},
        regime_info=_bull(),
    )
    assert out["gates"]["passed"] is True
    assert out["size_mult"] == 1.0
    assert out["final_score"] >= SCORE.FINAL_WATCHLIST
    if out["keputusan"] == "STRONG BUY" and out["timing_layak_entry"]:
        assert out["eligible_for_buy"] is True


def test_compute_layered_extreme_not_eligible():
    out = ls.compute_layered_score(
        sharia={"compliant": True},
        fund={"magic_score": 6, "raw": {"per": 10, "roe": 20}},
        cslim={"canslim_score": 6},
        tech=_liq_ok_tech(),
        regime_info=_extreme(),
    )
    assert out["gates"]["passed"] is False
    assert out["keputusan"] == "SKIP"
    assert out["eligible_for_buy"] is False
    assert out["final_score"] == 0.0


def test_compute_layered_bearish_non_extreme_defensive():
    out = ls.compute_layered_score(
        sharia={"compliant": True},
        fund={"magic_score": 5, "raw": {"per": 12, "roe": 16, "dividend_yield": 6}},
        cslim={"canslim_score": 4},
        tech=_liq_ok_tech(),
        regime_info=ls.classify_regime_ma(970, 1000),  # bearish non-extreme
    )
    # defensif auto dari DY → mult 0.5
    assert out["defensive"] is True
    assert out["size_mult"] == 0.5
    assert out["gates"]["passed"] is True  # bukan ekstrem


def test_quality_formula_example_bris_row():
    """Contoh baris BRIS: bobot spreadsheet → Quality 85.0 (Final=Quality saat ×1)."""
    # Fund85 Tek75 Bandar80 Liq90 IHSG70 Risk85
    q = (
        85 * 0.30 + 75 * 0.20 + 80 * 0.15
        + 90 * 0.15 + 70 * 0.15 + 85 * 0.10
    )
    assert abs(q - 85.0) < 1e-9
    assert ls.decide_final(q) == "STRONG BUY"


def test_decide_final_bands():
    assert ls.decide_final(80) == "STRONG BUY"
    assert ls.decide_final(60) == "WATCHLIST"
    assert ls.decide_final(40) == "SKIP"


def test_legacy_score_range():
    skor = ls.legacy_score(
        {"magic_score": 4},
        {"canslim_score": 4},
        {"ok": True, "bias": "BULLISH"},
        {"ok": True, "score": 2},
        {"signal": "BUY"},
    )
    assert 0 <= skor <= 100
