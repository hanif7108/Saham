"""Unit test fungsi murni (tanpa jaringan) — divalidasi ke contoh di modul."""

import numpy as np
import pandas as pd

from app.core import technical, trading_plan as tp


# ----- Money Management (modul hal. 53) -----------------------------------
def test_money_management():
    r = tp.money_management(10_000_000, num_stocks=2)
    assert r["trading_fund"] == 5_000_000      # 50%
    assert r["bid_fund_per_saham"] == 2_500_000
    assert r["loss_fund_per_saham"] == 75_000   # 3%
    assert r["profit_fund_per_saham"] == 150_000  # 6%


# ----- Position sizing (modul hal. 55): 5jt / 4200 / 100 = 11 lot ---------
def test_position_size():
    r = tp.position_size(5_000_000, 4200)
    assert r["lot"] == 11
    assert r["lembar"] == 1100


# ----- Taichi alokasi lot (modul hal. 55) ---------------------------------
def test_taichi_konservatif():
    r = tp.taichi_plan(5_000_000, 4200, mode="konservatif")
    lots = [o["lot"] for o in r["open_buy"]]
    assert lots == [2, 3, 6]            # rasio 2:4:8 /14 dari 11 lot
    assert sum(lots) == 11


def test_taichi_moderat():
    r = tp.taichi_plan(5_000_000, 4200, mode="moderat")
    lots = [o["lot"] for o in r["open_buy"]]
    assert lots == [3, 3, 5]            # 30/30/40 dari 11 lot


def test_taichi_average():
    # contoh modul hal. 56: Ob1 4200x1, Ob2 4130x2 -> avg 4153.3
    avg = ((4200 * 1) + (4130 * 2)) / 3
    assert round(avg, 1) == 4153.3


# ----- Fraksi harga BEI ----------------------------------------------------
def test_bei_tick():
    assert tp.bei_tick(150) == 1
    assert tp.bei_tick(300) == 2
    assert tp.bei_tick(1000) == 5
    assert tp.bei_tick(4200) == 10
    assert tp.bei_tick(6000) == 25


# ----- RRR (modul hal. 52): beli 30000, CL 28000, TP 34000 = 1:2 ----------
def test_rrr():
    r = tp.risk_reward(30_000, 28_000, 34_000)
    assert r["rrr_value"] == 2.0
    assert r["layak"] is True


def test_rrr_auto_tp():
    r = tp.risk_reward(1000, 950, target_reward_mult=2)
    assert r["take_profit"] == 1100   # 1000 + (50*2)
    assert r["rrr_value"] == 2.0


def test_rrr_invalid():
    r = tp.risk_reward(1000, 1100)    # CL di atas beli -> invalid
    assert "error" in r


# ----- Indikator teknikal (sintetis) --------------------------------------
def _df(prices):
    return pd.DataFrame({
        "Open": prices, "High": [p * 1.01 for p in prices],
        "Low": [p * 0.99 for p in prices], "Close": prices,
        "Volume": [1000] * len(prices),
    })


def test_sma():
    s = technical.sma(pd.Series([1, 2, 3, 4, 5]), 5)
    assert s.iloc[-1] == 3.0


def test_stochastic_range():
    prices = list(np.linspace(100, 200, 60))
    k, d = technical.stochastic(_df(prices), 14, 3, 3)
    assert 0 <= k.iloc[-1] <= 100
    # tren naik konsisten -> stochastic tinggi (overbought)
    assert k.iloc[-1] > 80


# ----- Support / Resistance multi-level ------------------------------------
def test_sr_levels_classify_and_strength():
    # harga berosilasi antara ~100 (support) dan ~120 (resistance), tutup di tengah
    cycle = [100, 108, 120, 108, 100, 108, 120, 108]
    prices = (cycle * 8) + [110]
    df = _df(prices)
    levels = technical.support_resistance_levels(df, lookback=60, window=2, max_levels=6)
    assert levels, "harus menemukan minimal satu zona S/R"
    # setiap zona: support di bawah harga terakhir, resistance di atas
    price = prices[-1]
    for lv in levels:
        assert lv["jenis"] == ("support" if lv["level"] < price else "resistance")
        assert lv["kekuatan"] >= 1
    # area berulang -> ada zona dengan >1 sentuhan (ter-cluster)
    assert max(l["kekuatan"] for l in levels) >= 2


def test_sr_levels_empty_on_short_data():
    assert technical.support_resistance_levels(_df([100, 101, 102]), 60, 5) == []


def test_atr_and_adx():
    # Buat data sintetis trend naik
    prices = list(range(100, 130))  # 30 hari naik terus
    highs = [p + 2 for p in prices]
    lows = [p - 2 for p in prices]
    closes = prices
    df = pd.DataFrame({
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Open": prices,
        "Volume": [1000] * len(prices)
    })
    
    atr_val = technical.atr(df, 14)
    assert len(atr_val) == len(df)
    assert atr_val.iloc[-1] > 0
    
    plus_di, minus_di, adx_val = technical.adx(df, 14)
    assert len(adx_val) == len(df)
    # tren naik yang kuat -> +DI > -DI dan ADX tinggi (> 20)
    assert plus_di.iloc[-1] > minus_di.iloc[-1]
    assert adx_val.iloc[-1] > 20


def test_bandarmologi_proxy():
    # Buat data sintetis di mana harga naik pada volume tinggi (akumulasi)
    prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115]
    volumes = [1000] * 5 + [2000] * 5 + [5000] * 6
    highs = [p + 1 for p in prices]
    lows = [p - 1 for p in prices]
    # Tutup dekat High untuk akumulasi (CLV > 0)
    closes = highs
    df = pd.DataFrame({
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Open": prices,
        "Volume": volumes
    })
    
    from app.core import bandarmologi
    res = bandarmologi.get_bandar_analysis("TEST_TICKER", hist=df)
    assert res["ticker"] == "TEST_TICKER"
    # CMF harus positif karena penutupan mendekati high pada volume meningkat
    assert res["cmf"] > 0
    assert res["sentiment"] in ("AKUMULASI", "AKUMULASI BESAR")
    assert res["layak_beli"] is True


def test_bandarmologi_distrib():
    # Buat data sintetis di mana harga turun pada volume tinggi (distribusi)
    prices = [120, 119, 118, 117, 116, 115, 114, 113, 112, 111, 110, 109, 108, 107, 106, 105]
    volumes = [1000] * 5 + [2000] * 5 + [5000] * 6
    highs = [p + 1 for p in prices]
    lows = [p - 1 for p in prices]
    # Tutup dekat Low untuk distribusi (CLV < 0)
    closes = lows
    df = pd.DataFrame({
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Open": prices,
        "Volume": volumes
    })
    
    from app.core import bandarmologi
    res = bandarmologi.get_bandar_analysis("TEST_TICKER", hist=df)
    assert res["ticker"] == "TEST_TICKER"
    # CMF harus negatif karena penutupan mendekati low pada volume meningkat
    assert res["cmf"] < 0
    assert res["sentiment"] in ("DISTRIBUSI", "DISTRIBUSI BESAR")
    assert res["layak_beli"] is False


def test_fibonacci_calculation():
    # Buat data naik lurus dari 100 ke 200 selama 60 hari
    dates = pd.date_range(end="2026-06-19", periods=60)
    prices = list(np.linspace(100, 200, 60))
    df = pd.DataFrame({
        "Open": prices,
        "High": prices,
        "Low": prices,
        "Close": prices,
        "Volume": [1000] * 60
    }, index=dates)
    
    res = technical.calculate_fibonacci(df, lookback=60)
    
    assert res["uptrend_direction"] is True
    assert res["max_high"] == 200.0
    assert res["min_low"] == 100.0
    assert res["levels"]["level_50.0"] == 150.0
    assert res["levels"]["level_61.8"] == 138.2
    
    # Periksa time cycles
    assert len(res["time_cycles"]) == 6
    assert res["time_cycles"][0]["cycle"] == 8
    assert "date" in res["time_cycles"][0]
    
    # Periksa full technical analysis integration
    import os
    from app.config import BASE_DIR
    log_file = BASE_DIR.parent / "data_store" / "astronacci_cycles.jsonl"
    if log_file.exists():
        try:
            os.remove(log_file)
        except Exception:
            pass

    tech_res = technical.analyze_technical("TEST_FIB", hist=df)
    assert "fibonacci" in tech_res
    assert tech_res["fibonacci"]["levels"]["level_50.0"] == 150.0
    assert "closest_level_note" in tech_res["fibonacci"]
    
    # Periksa bahwa pencatatan data science berfungsi
    assert log_file.exists()
    content = log_file.read_text()
    assert "TEST_FIB" in content

    # Periksa integrasi rekomendasi funnel
    from app.core import funnel
    sharia = {"compliant": True, "catatan": ""}
    fund = {"magic_score": 5, "fundamental_label": "BUY", "checks": []}
    cslim = {"canslim_score": 6, "verdict": "PASS", "letters": {}}
    j7 = {"score": 3, "verdict": "PASS", "ok": True}
    osignal = {"signal": "BUY"}
    bandar = {"layak_beli": True, "sentiment": "AKUMULASI", "score": 80, "note": ""}
    
    rec_res = funnel._recommend(sharia, fund, cslim, tech_res, j7, osignal, bandar)
    fibo_reasons = [r for r in rec_res["alasan"] if "Fibonacci:" in r]
    assert len(fibo_reasons) > 0
    assert "Proyeksi Reversal" in fibo_reasons[0]


def test_volume_profile_and_vip_rating():
    # Buat data sintetis
    dates = pd.date_range(end="2026-06-20", periods=60, freq="B")
    prices = [100.0 + i for i in range(60)] # tren naik: 100 s/d 159
    # low, high, close, open
    df = pd.DataFrame({
        "Open": prices,
        "High": [p + 1.0 for p in prices],
        "Low": [p - 1.0 for p in prices],
        "Close": prices,
        "Volume": [1000.0] * 60
    }, index=dates)
    
    # 1. Test calculate_volume_profile
    vp = technical.calculate_volume_profile(df)
    assert vp["poc"] is not None
    assert vp["vah"] is not None
    assert vp["val"] is not None
    assert len(vp["bins"]) == 20
    
    # 2. Test calculate_volatility_insight_pro_rating
    vip = technical.calculate_volatility_insight_pro_rating(
        df=df,
        trend="UPTREND",
        s50=120.0,
        s200=90.0,
        stoch_signal="golden cross (sinyal beli)",
        patterns=["Hammer (bullish)"],
        vp_data=vp
    )
    assert 1.0 <= vip["rating"] <= 5.0
    assert vip["conviction"] is not None
    assert len(vip["details"]) > 0
