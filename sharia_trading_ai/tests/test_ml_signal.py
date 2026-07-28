"""Test kontrak fitur ML, anti-look-ahead label, dan fallback runtime."""

import numpy as np
import pandas as pd
import pytest

from app.ml.features import (
    FEATURE_COLUMNS, LABEL_THRESHOLDS, add_labels, build_features,
)


def _synthetic_ohlcv(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    close = 1000 * np.cumprod(1 + rng.normal(0.0005, 0.02, n))
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    open_ = low + (high - low) * rng.random(n)
    vol = rng.integers(1_000_000, 50_000_000, n).astype(float)
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low,
                       "Close": close, "Adj Close": close, "Volume": vol},
                      index=idx)
    return df


@pytest.fixture()
def ohlcv():
    return _synthetic_ohlcv()


@pytest.fixture()
def market():
    return _synthetic_ohlcv(seed=99)


def test_feature_columns_contract(ohlcv, market):
    feats = build_features(ohlcv, market)
    assert list(feats.columns) == FEATURE_COLUMNS
    # setelah warm-up 260 bar, tidak boleh ada NaN pada fitur inti
    tail = feats.iloc[300:]
    for col in ("rsi14", "close_sma200", "dist_high52w", "vol_ratio20"):
        assert tail[col].notna().all(), col


def test_features_no_lookahead(ohlcv, market):
    """Fitur pada bar t tidak boleh berubah bila data setelah t diubah."""
    full = build_features(ohlcv, market)
    cut = 350
    truncated = build_features(ohlcv.iloc[:cut], market.iloc[:cut])
    a = full.iloc[cut - 1]
    b = truncated.iloc[-1]
    pd.testing.assert_series_equal(a, b, check_names=False)


def test_labels_use_forward_prices_only(ohlcv, market):
    feats = build_features(ohlcv, market)
    lab = add_labels(feats, ohlcv, horizons=(5,))
    adj = ohlcv["Adj Close"]
    t = 100
    expected = adj.iloc[t + 5] / adj.iloc[t] - 1
    assert lab["fwd_ret_5"].iloc[t] == pytest.approx(expected)
    # N bar terakhir tidak punya label (tidak ada harga forward)
    assert lab["fwd_ret_5"].iloc[-5:].isna().all()
    thr = LABEL_THRESHOLDS[5]
    lbl = lab.dropna(subset=["label_5"])
    assert ((lbl["fwd_ret_5"] > thr) == (lbl["label_5"] == 1)).all()


def test_labels_mask_anomalies(ohlcv, market):
    df = ohlcv.copy()
    # suntik anomali: harga meloncat 10x pada satu hari (split tak tercatat)
    df.iloc[200, df.columns.get_loc("Adj Close")] *= 10
    feats = build_features(df, market)
    lab = add_labels(feats, df, horizons=(5,))
    # bar 195..200 memuat anomali di jendela forward-nya -> label NaN
    assert lab["label_5"].iloc[195:201].isna().all()


def test_predict_graceful_without_enough_data(monkeypatch):
    from app.core import ml_signal
    tiny = _synthetic_ohlcv(n=50)
    res = ml_signal.predict("KLBF", hist=tiny, index_hist=tiny)
    assert res["available"] is False


def test_predict_unavailable_artifact(monkeypatch, ohlcv, market):
    from app.core import ml_signal
    monkeypatch.setattr(ml_signal, "_load", lambda h, v="": None)
    res = ml_signal.predict("KLBF", hist=ohlcv, index_hist=market)
    assert res["available"] is False
    assert "artifact" in res["reason"]


def test_watchlist_ml_active_veto_and_buy(monkeypatch):
    from app.config import settings
    from app.core import decisions, ml_signal

    monkeypatch.setattr(settings, "ml_signal_mode", "active", raising=False)
    from app.core import bandarmologi
    monkeypatch.setattr(bandarmologi, "get_bandar_analysis",
                        lambda tk, **kw: {"layak_beli": True})

    base = {"ticker": "KLBF", "trend": "UPTREND", "fundamental_score": 5,
            "fundamental_max": 7, "technical_signal": "HOLD", "rsi": 55,
            "ma_cross": "GOLDEN", "sector": "Healthcare", "jalur7": {}}

    sell = {**base, "ml_signal": {"available": True, "signal": "SELL",
                                  "confident": True, "p_buy": 0.1}}
    assert decisions.decide_for_watchlist(sell, set(), {}) is None

    buy = {**base, "ml_signal": {"available": True, "signal": "BUY",
                                 "confident": True, "p_buy": 0.61,
                                 "horizon": 5}}
    res = decisions.decide_for_watchlist(buy, set(), {})
    assert res is not None and res["action"] == "BUY"
    assert res["context"] == "ML_SIGNAL"

    # shadow mode: sinyal ML yang sama TIDAK mengubah keputusan
    monkeypatch.setattr(settings, "ml_signal_mode", "shadow", raising=False)
    res_shadow = decisions.decide_for_watchlist(buy, set(), {})
    assert res_shadow is None or res_shadow.get("context") != "ML_SIGNAL"
