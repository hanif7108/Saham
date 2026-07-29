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


def test_log_idempotent(isolated_store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ml_horizon", 5, raising=False)  # selaras fake
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


def test_tick_size_and_slippage_bei():
    from app.ml.train import tick_size, slippage_roundtrip
    assert tick_size(150) == 1 and tick_size(350) == 2 and tick_size(1500) == 5
    assert tick_size(3000) == 10 and tick_size(8000) == 25
    # saham murah: slippage relatif jauh lebih besar
    assert slippage_roundtrip(200) == pytest.approx(2*2/200)     # 2.0%
    assert slippage_roundtrip(5000) == pytest.approx(2*25/5000)  # 1.0%
    assert slippage_roundtrip(1000) == pytest.approx(2*5/1000)   # 1.0%
    assert slippage_roundtrip(0) == 0.0


def test_simulate_applies_price_slippage():
    from app.ml import train as T
    dates = pd.bdate_range("2024-01-01", periods=1)
    df = pd.DataFrame({
        "date": list(dates)*2, "ticker": ["A","B"],
        "fwd_ret_10": [0.05, 0.05], "price": [200.0, 5000.0],
        "sig": [True, True], "rank": [2.0, 1.0],
    })
    bt = T.simulate(df, 10, "sig", "rank", top_k=2, cost=0.004)
    # return bersih = 5% - 0.4% - rata2 slippage (2% & 1%) = 3.1%
    assert bt["avg_period_ret"] == pytest.approx(0.05 - 0.004 - (0.02+0.01)/2, abs=1e-4)


def test_log_transition_day_two_horizons(isolated_store, monkeypatch):
    """Hari transisi: batch horizon lama & baru boleh hidup berdampingan."""
    from app.config import settings
    monkeypatch.setattr(tracker, "_is_market_data_final", lambda d: True)
    r1 = tracker.log_today(ranking=_fake_ranking(), force=True)   # horizon 5 (fake)
    assert r1["logged"] == 2
    # ganti horizon aktif -> pencatatan kedua TIDAK dianggap duplikat
    monkeypatch.setattr(settings, "ml_horizon", 7, raising=False)
    fake2 = _fake_ranking()
    for s in fake2:
        if s["ml_signal"].get("available"):
            s["ml_signal"]["horizon"] = 7
    r2 = tracker.log_today(ranking=fake2)
    assert r2.get("logged") == 2
    # horizon sama -> duplikat ditolak
    r3 = tracker.log_today(ranking=fake2)
    assert r3.get("skipped") == "sudah tercatat"
    df = pd.read_parquet(tracker.STORE)
    assert len(df) == 4 and sorted(df["horizon"].unique()) == [5, 7]


def test_telegram_top_respects_min_price(isolated_store):
    ranking = _fake_ranking()
    ranking[0]["current_price"] = 300.0   # KLBF di bawah Rp500
    tracker.log_today(ranking=ranking, force=True)
    df = pd.read_parquet(tracker.STORE)
    txt = tracker.build_telegram_text(df, {})
    assert "KLBF" not in txt.split("Peringatan")[0]   # tidak masuk top pilihan


def test_closing_message_compares_intraday_snapshot(isolated_store, monkeypatch):
    import json as _json
    monkeypatch.setattr(tracker, "INTRADAY_SNAPSHOT",
                        tracker.STORE.parent / "intraday_snapshot.json")
    # snapshot 15:30: EMTK direkomendasikan di Rp515
    tracker.INTRADAY_SNAPSHOT.write_text(_json.dumps({
        "date": tracker.today_wib().isoformat(), "label": "15:30 WIB",
        "picks": [{"ticker": "EMTK", "price": 515.0, "p_buy": 0.7}]}))
    rows = pd.DataFrame([{  # baris store penutupan: EMTK tutup di Rp525
        "date": tracker.today_wib().isoformat(), "ticker": "EMTK",
        "signal": "BUY", "p_buy": 0.73, "p_hold": 0.2, "p_sell": 0.07,
        "confident": True, "price": 525.0, "rule_signal": "SKIP",
        "horizon": 10}])
    txt = tracker.build_telegram_text(rows, {})
    assert "Sinyal 15:30 WIB → penutupan" in txt
    assert "EMTK Rp515 → Rp525 (+1.94%) ✅" in txt
    # snapshot kemarin -> tidak ditampilkan
    tracker.INTRADAY_SNAPSHOT.write_text(_json.dumps({
        "date": "2020-01-01", "label": "15:30 WIB",
        "picks": [{"ticker": "EMTK", "price": 515.0, "p_buy": 0.7}]}))
    txt2 = tracker.build_telegram_text(rows, {})
    assert "→ penutupan" not in txt2


def test_intraday_scan_archive_appends(isolated_store, monkeypatch):
    monkeypatch.setattr(tracker, "INTRADAY_SCANS",
                        tracker.STORE.parent / "intraday_scans.parquet")
    rows = pd.DataFrame([
        {"date": "2026-07-29", "ticker": "EMTK", "signal": "BUY", "p_buy": .7,
         "p_hold": .2, "p_sell": .1, "confident": True, "price": 520.0,
         "horizon": 10},
        {"date": "2026-07-29", "ticker": "ANTM", "signal": "HOLD", "p_buy": .3,
         "p_hold": .5, "p_sell": .2, "confident": False, "price": 2900.0,
         "horizon": 10}])
    tracker._append_intraday_scan(rows, "09:30 WIB")
    tracker._append_intraday_scan(rows, "15:30 WIB")
    df = pd.read_parquet(tracker.INTRADAY_SCANS)
    assert len(df) == 4                                   # append, tidak menimpa
    assert sorted(df["scan_label"].unique()) == ["09:30 WIB", "15:30 WIB"]
    assert "scanned_at" in df.columns and df["scanned_at"].str.contains("\\+07:00").all()


def _make_candidate(tmp_path, monkeypatch, with_metrics=True, with_promote=True,
                    feats=None):
    import json as _json, lightgbm as lgb, numpy as np
    from app.ml import model_ingest as MI
    from app.ml.features import FEATURE_COLUMNS
    feats = feats or FEATURE_COLUMNS
    cdir = tmp_path / "cand" / "20260728_rig"; cdir.mkdir(parents=True)
    X = np.random.default_rng(1).normal(size=(300, len(feats)))
    y = (X[:, 0] > 0).astype(int)
    m = lgb.train({"objective": "binary", "verbosity": -1},
                  lgb.Dataset(X, label=y), num_boost_round=5)
    m.save_model(str(cdir / "ml_signal_h10.txt"))
    meta = {"engine": "lightgbm", "model_file": "ml_signal_h10.txt",
            "horizon": 10, "feature_columns": list(feats)}
    if with_metrics:
        meta["walkforward_metrics"] = {"sharpe": 0.5}
    (cdir / "ml_signal_h10.meta.json").write_text(_json.dumps(meta))
    if with_promote:
        (cdir / "PROMOTE").touch()
    monkeypatch.setattr(MI, "CANDIDATE_DIR", tmp_path / "cand")
    monkeypatch.setattr(MI, "ARTIFACT_DIR", tmp_path / "artifacts")
    (tmp_path / "artifacts").mkdir()
    monkeypatch.setattr(MI, "ML_DATA_DIR", tmp_path)
    return MI, cdir


def test_model_ingest_promotes_valid_candidate(tmp_path, monkeypatch):
    MI, cdir = _make_candidate(tmp_path, monkeypatch)
    out = MI.run()
    assert out["results"][0]["ok"] and out["results"][0]["promoted"]
    assert (tmp_path / "artifacts" / "ml_signal_h10.txt").exists()
    assert (cdir / "PROMOTED_AT").exists() and not (cdir / "PROMOTE").exists()


def test_model_ingest_rejects_without_metrics_or_features(tmp_path, monkeypatch):
    MI, _ = _make_candidate(tmp_path, monkeypatch, with_metrics=False)
    out = MI.run()
    assert not out["results"][0]["ok"]
    assert "walkforward_metrics" in out["results"][0]["reason"]

    MI2, _ = _make_candidate(tmp_path / "b", monkeypatch,
                             feats=["fitur_asing", "lainnya"])
    out2 = MI2.run()
    assert not out2["results"][0]["ok"]
    assert "fitur" in out2["results"][0]["reason"]


def test_model_ingest_no_promote_marker_means_no_install(tmp_path, monkeypatch):
    MI, _ = _make_candidate(tmp_path, monkeypatch, with_promote=False)
    out = MI.run()
    r = out["results"][0]
    assert r["ok"] and not r["promoted"] and not r["has_promote"]
    assert not (tmp_path / "artifacts" / "ml_signal_h10.txt").exists()


def test_exit_rules_matrix():
    from app.core.exit_rules import evaluate_exit
    ml_weak = {"available": True, "p_buy": 0.2, "p_hold": 0.5, "p_sell": 0.3, "signal": "HOLD"}
    # SL menang atas segalanya
    assert evaluate_exit(pnl_pct=-8, price=92, peak_price=100, avg_price=100,
                         days_held=5)["kode"] == "CUT_LOSS"
    # TP (default 10%)
    assert evaluate_exit(pnl_pct=11, price=111, peak_price=111, avg_price=100,
                         days_held=5)["kode"] == "TAKE_PROFIT"
    # Trailing trigger: pernah +8%, kini turun 4% dari puncak
    v = evaluate_exit(pnl_pct=3.7, price=103.7, peak_price=108, avg_price=100,
                      days_held=5)
    assert v["kode"] == "TRAILING" and v["action"] == "SELL"
    # Trailing armed (belum trigger): puncak +8%, turun cuma 1%
    v = evaluate_exit(pnl_pct=6.9, price=106.9, peak_price=108, avg_price=100,
                      days_held=5)
    assert v["kode"] == "TRAIL_ARMED" and v["action"] == "TRAIL"
    # Time-stop: 25 hari, belum target, ML lemah
    v = evaluate_exit(pnl_pct=1.0, price=101, peak_price=103, avg_price=100,
                      days_held=25, ml=ml_weak)
    assert v["kode"] == "TIME_STOP" and v["action"] == "SELL"
    # Time-stop TIDAK terpicu bila ML masih mendukung
    ml_kuat = {**ml_weak, "p_buy": 0.55, "signal": "BUY"}
    assert evaluate_exit(pnl_pct=1.0, price=101, peak_price=103, avg_price=100,
                         days_held=25, ml=ml_kuat)["kode"] == "HOLD"
    # Peringatan ML SELL
    ml_sell = {"available": True, "p_buy": 0.1, "p_hold": 0.4, "p_sell": 0.5, "signal": "SELL"}
    assert evaluate_exit(pnl_pct=2.0, price=102, peak_price=103, avg_price=100,
                         days_held=3, ml=ml_sell)["kode"] == "ML_SELL_WARN"


def test_telegram_positions_section(isolated_store, monkeypatch):
    import pandas as _pd
    from app.core import portfolio as pf
    monkeypatch.setattr(pf, "list_positions", lambda: {"positions": [
        {"ticker": "KLBF", "broker": "Profits Anywhere", "pl_pct": 3.7,
         "current_price": 1560.0, "avg_price": 1505.0, "added_at": "2026-07-01"},
        {"ticker": "AAPL", "broker": "Pluang", "pl_pct": -8.2,
         "current_price": 210.0, "avg_price": 229.0, "added_at": "2026-06-01"},
    ]})
    from app.data import provider
    idx = _pd.bdate_range("2026-05-01", periods=60)
    fake_hist = _pd.DataFrame({"Close": [1500.0]*40 + [1625.0] + [1560.0]*19}, index=idx)
    monkeypatch.setattr(provider, "get_history", lambda tk, **kw: fake_hist)
    from app.core import ml_signal as mls
    monkeypatch.setattr(mls, "scan_universe", lambda **kw: {"signals": []})
    lines = tracker._positions_lines()
    txt = "\n".join(lines)
    assert "Posisi Anda" in txt
    assert "KLBF" in txt and "Profits Anywhere" in txt
    assert "AAPL" in txt and "CUT_LOSS" not in txt  # alasan pakai kalimat, bukan kode
    assert "🔴" in txt   # AAPL -8.2% -> SELL cut loss


def test_portfolio_snapshot_and_monthly_roi(tmp_path, monkeypatch):
    import json as _json
    from app.core import portfolio_snapshot as PS
    monkeypatch.setattr(PS, "SNAP_DIR", tmp_path)
    # dua snapshot berjarak ~30 hari, basis modal sama -> ROI presisi
    for d, v in (("2026-06-28", 15_000_000), ("2026-07-28", 16_200_000)):
        (tmp_path / f"portfolio_{d}.json").write_text(_json.dumps({
            "date": d, "summary": {"total_net_value": v, "total_cost": 15_000_000},
            "positions": []}))
    roi = PS.monthly_roi()
    assert roi and roi["roi_pct"] == 8.0 and roi["target_pct"] == 10.0
    assert not roi["approx_basis_changed"]
    # basis berubah (ada beli baru) -> ditandai approx
    (tmp_path / "portfolio_2026-07-28.json").write_text(_json.dumps({
        "date": "2026-07-28", "summary": {"total_net_value": 20_000_000,
                                          "total_cost": 19_000_000},
        "positions": []}))
    roi2 = PS.monthly_roi()
    assert roi2 and roi2["approx_basis_changed"]


def test_morning_briefing_recap_only_at_0830(isolated_store, monkeypatch):
    import pandas as _pd
    from app.data import provider
    idx = _pd.bdate_range("2025-08-01", periods=250)
    ihsg = _pd.DataFrame({"Close": [6000.0]*248 + [6200.0, 6184.0]}, index=idx)
    monkeypatch.setattr(provider, "get_index_history", lambda **kw: ihsg)
    monkeypatch.setattr(provider, "get_history", lambda tk, **kw: ihsg)
    from app.core import portfolio as pf
    monkeypatch.setattr(pf, "list_positions", lambda: {"positions": []})
    tracker.log_today(ranking=_fake_ranking(), force=True)
    df = tracker._load()
    pagi = tracker.build_telegram_text(df, {}, label="08:30 WIB")
    sore = tracker.build_telegram_text(df, {}, label="penutupan · 16:30 WIB")
    assert "Briefing Pagi" in pagi and "Rekap pasar kemarin" in pagi
    assert "IHSG" in pagi and "-0.26%" in pagi          # 6184/6200-1
    assert "Rekap pasar kemarin" not in sore and "Sinyal ML Harian" in sore


def test_exit_rules_accepts_scan_shaped_ml():
    """Baris scan tanpa key 'available' HARUS tetap memicu aturan ML."""
    from app.core.exit_rules import evaluate_exit
    scan_ml = {"signal": "SELL", "p_buy": 0.1, "p_hold": 0.4, "p_sell": 0.5}
    v = evaluate_exit(pnl_pct=2.0, price=102, peak_price=103, avg_price=100,
                      days_held=3, ml=scan_ml)
    assert v["kode"] == "ML_SELL_WARN"          # dulu bug: tak pernah terpicu
    # time-stop juga hidup dgn ml scan-shaped lemah
    weak = {"signal": "HOLD", "p_buy": 0.2, "p_hold": 0.6, "p_sell": 0.2}
    v2 = evaluate_exit(pnl_pct=1.0, price=101, peak_price=102, avg_price=100,
                       days_held=25, ml=weak)
    assert v2["kode"] == "TIME_STOP"


def test_narrative_grounded_in_features():
    from app.ml import narrator
    fake_pr = {"available": True, "p_buy": 0.71, "p_sell": 0.06,
               "top_features": [
                   {"feature": "close_sma200", "importance": .1, "value": 0.18},
                   {"feature": "rs_60", "importance": .08, "value": 0.12},
                   {"feature": "vol_ratio20", "importance": .05, "value": 2.1},
                   {"feature": "month", "importance": .04, "value": 7.0}]}
    txt = narrator.build_narrative(
        [{"ticker": "ANTM", "name": "Aneka Tambang", "price": 2900,
          "rule_signal": "SKIP"}], "08:30 WIB", predict_fn=lambda tk: fake_pr)
    assert txt and "ANTM" in txt and "P(BUY) 71%" in txt
    assert "18% di atas rata-rata 200 hari" in txt      # dari nilai fitur nyata
    assert "mengungguli IHSG +12%" in txt
    assert "volume 2.1×" in txt
    assert "Pelajaran" in txt and "SKIP" in txt
    # tanpa kandidat -> None (tidak kirim pesan kosong)
    assert narrator.build_narrative([], None) is None
