"""Test lingkaran belajar prediksi-vs-realisasi (app/ml/tracker.py)."""

import numpy as np
import pandas as pd
import pytest

from app.ml import tracker


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker, "STORE", tmp_path / "ml_track.parquet")
    monkeypatch.setattr(tracker, "SUMMARY", tmp_path / "ml_track_summary.json")
    return tmp_path


def _fake_ranking():
    return [
        {"ticker": "KLBF", "current_price": 1500.0, "final_signal": "BUY",
         "skor": 62.0, "keputusan": "WATCHLIST",
         "ml_signal": {"available": True, "signal": "BUY", "p_buy": 0.52,
                        "p_hold": 0.3, "p_sell": 0.18, "confident": True,
                        "horizon": 5}},
        {"ticker": "ANTM", "current_price": 2000.0, "final_signal": "SKIP",
         "skor": 40.0, "keputusan": "SKIP",
         "ml_signal": {"available": True, "signal": "SELL", "p_buy": 0.2,
                        "p_hold": 0.3, "p_sell": 0.5, "confident": True,
                        "horizon": 5}},
        {"ticker": "AAPL.US", "current_price": 200.0, "final_signal": "BUY",
         "skor": 70.0, "ml_signal": {"available": False}},
    ]


def test_log_idempotent(isolated_store):
    r1 = tracker.log_today(ranking=_fake_ranking(), force=True)
    assert r1["ok"] and r1["logged"] == 2   # AAPL.US (US/unavailable) dilewati
    r2 = tracker.log_today(ranking=_fake_ranking())
    assert r2.get("skipped") == "sudah tercatat"
    df = pd.read_parquet(tracker.STORE)
    assert len(df) == 2
    assert not df["evaluated"].any()


def _hist(days_after: int, up: bool):
    """History harian: bar log hari ini + `days_after` bar sesudahnya."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=30)
    idx = idx.append(pd.bdate_range(idx[-1] + pd.Timedelta(days=1),
                                    periods=days_after))
    base = 1000.0
    close = np.full(len(idx), base)
    # setelah tanggal log, harga bergerak 1%/hari ke arah `up`
    n0 = 30
    for i in range(n0, len(idx)):
        close[i] = close[i - 1] * (1.01 if up else 0.99)
    return pd.DataFrame({"Close": close}, index=idx)


def test_evaluate_waits_for_horizon(isolated_store, monkeypatch):
    tracker.log_today(ranking=_fake_ranking(), force=True)
    from app.data import provider
    # baru 3 bar setelah log -> horizon 5 belum jatuh tempo
    monkeypatch.setattr(provider, "get_history",
                        lambda tk, **kw: _hist(3, up=True))
    res = tracker.evaluate_matured()
    assert res["evaluated"] == 0


def test_evaluate_scores_direction(isolated_store, monkeypatch):
    tracker.log_today(ranking=_fake_ranking(), force=True)
    from app.data import provider

    def fake_history(tk, **kw):
        return _hist(6, up=(tk == "KLBF"))   # KLBF naik, ANTM turun

    monkeypatch.setattr(provider, "get_history", fake_history)
    res = tracker.evaluate_matured()
    assert res["evaluated"] == 2
    df = pd.read_parquet(tracker.STORE)
    by = df.set_index("ticker")
    # KLBF: BUY & naik ~5% -> outcome 1, benar; ANTM: SELL & turun -> benar
    assert by.loc["KLBF", "outcome"] == 1 and bool(by.loc["KLBF", "ml_correct"])
    assert by.loc["ANTM", "outcome"] == -1 and bool(by.loc["ANTM", "ml_correct"])
    s = tracker.stats()
    assert s["evaluated"] == 2
    assert s["by_signal"]["BUY"]["hit_rate"] == 1.0


def test_calibration_needs_samples(isolated_store):
    tracker.log_today(ranking=_fake_ranking(), force=True)
    cal = tracker.calibrate()
    assert cal["ok"] is False   # < 30 sampel BUY terevaluasi


def test_calibrated_threshold_flows_to_predict(isolated_store, monkeypatch):
    # summary dengan kalibrasi ok -> ml_signal memakai ambang tsb
    tracker.SUMMARY.write_text(
        '{"calibration": {"ok": true, "suggested_conf_threshold": 0.5}}')
    assert tracker.calibrated_threshold() == 0.5


def test_build_telegram_text(isolated_store):
    tracker.log_today(ranking=_fake_ranking(), force=True)
    df = pd.read_parquet(tracker.STORE)
    txt = tracker.build_telegram_text(df, {})
    assert "Sinyal ML Harian" in txt
    assert "KLBF" in txt and "52%" in txt          # top BUY + probabilitasnya
    assert "ANTM 50%" in txt                        # peringatan SELL
    assert "shadow" in txt
    # dengan track record terevaluasi -> baris track record ikut
    txt2 = tracker.build_telegram_text(df, {
        "evaluated": 10,
        "ml_buy_all": {"n": 5, "win_rate_pos": 0.6, "avg_ret_pct": 1.2},
        "rule_buyish": {"n": 4, "win_rate_pos": 0.5, "avg_ret_pct": 0.3}})
    assert "Track record" in txt2 and "60%" in txt2


def test_conventional_screen_top_k_per_day():
    from app.ml.dataset import apply_conventional_screen
    rng = np.random.default_rng(3)
    n_days, n_tk = 30, 25
    dates = np.repeat(pd.bdate_range("2024-01-01", periods=n_days), n_tk)
    rows = pd.DataFrame({
        "date": dates,
        "ticker": np.tile([f"TK{i:02d}" for i in range(n_tk)], n_days),
        "close_sma200": rng.normal(0.05, 0.1, len(dates)),
        "sma50_sma200": rng.normal(0.02, 0.05, len(dates)),
        "rsi14": rng.uniform(20, 90, len(dates)),
        "rs_60": rng.normal(0, 0.1, len(dates)),
        "ret_20": rng.normal(0, 0.08, len(dates)),
        "vol_ratio20": rng.uniform(0.5, 3, len(dates)),
    })
    scr = apply_conventional_screen(rows, top_k=10)
    # tidak pernah > 10 per hari, dan semua lolos gerbang uptrend/RSI
    assert scr.groupby("date").size().max() <= 10
    assert (scr["close_sma200"] > 0).all()
    assert (scr["sma50_sma200"] > 0).all()
    assert (scr["rsi14"] < 75).all()
    assert "conv_score" in scr.columns


def test_log_marks_focus_top10(isolated_store):
    ranking = _fake_ranking()
    ranking[0]["skor"] = 90.0   # KLBF skor tertinggi -> in_focus
    tracker.log_today(ranking=ranking, force=True)
    df = pd.read_parquet(tracker.STORE)
    assert bool(df.set_index("ticker").loc["KLBF", "in_focus"])


def test_cross_sectional_ranks_bounds():
    from app.ml.features import add_cross_sectional_ranks, CS_RANK_COLUMNS
    rng = np.random.default_rng(11)
    n_days, n_tk = 5, 8
    df = pd.DataFrame({
        "date": np.repeat(pd.bdate_range("2024-01-01", periods=n_days), n_tk),
        "ticker": np.tile([f"T{i}" for i in range(n_tk)], n_days),
        "ret_5": rng.normal(0, .05, n_days*n_tk), "ret_20": rng.normal(0, .1, n_days*n_tk),
        "rs_20": rng.normal(0, .05, n_days*n_tk), "rs_60": rng.normal(0, .1, n_days*n_tk),
        "vol_ratio20": rng.uniform(.5, 3, n_days*n_tk), "atr14_pct": rng.uniform(.01, .1, n_days*n_tk),
        "dist_high52w": rng.uniform(-.6, 0, n_days*n_tk), "turnover_log": rng.uniform(15, 25, n_days*n_tk),
    })
    out = add_cross_sectional_ranks(df)
    for c in CS_RANK_COLUMNS:
        assert out[c].between(0, 1).all()
        # dalam satu hari, ranking unik terisi merata
        assert out.groupby("date")[c].max().min() == 1.0
