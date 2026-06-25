"""
Analisa Teknikal (modul hal. 30-50).

Indikator & sinyal:
  - SMA 200 (filter tren utama) + SMA 20/50
  - Stochastic (%K, %D) — OB > 80 / OS < 20, golden/dead cross
  - Support & Resistance (swing pivot)
  - Klasifikasi tren: Uptrend / Downtrend / Sideways
  - Deteksi entry: FBO, 52WBO, BOR, BDTL, Buy on Pullback, Gap Up
  - Pola candlestick reversal (Hammer, Engulfing, Doji, Star, Harami)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.config import TECH
from app.data import provider


# --------------------------------------------------------------------------- #
#  Indikator dasar                                                            #
# --------------------------------------------------------------------------- #
def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def stochastic(df: pd.DataFrame, period: int, k_smooth: int, d_smooth: int) -> tuple[pd.Series, pd.Series]:
    """Stochastic Oscillator klasik (sesuai deskripsi modul: close vs lowest/highest)."""
    low_min = df["Low"].rolling(period).min()
    high_max = df["High"].rolling(period).max()
    raw_k = (df["Close"] - low_min) / (high_max - low_min).replace(0, np.nan) * 100
    k = raw_k.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return k, d


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's Smoothing)."""
    high = df["High"]
    low = df["Low"]
    close_prev = df["Close"].shift(1)
    
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_series = tr.ewm(alpha=1/period, adjust=False).mean()
    return atr_series


def adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Directional Movement Index (DMI): +DI, -DI, dan ADX (Wilder's Smoothing)."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    close_prev = close.shift(1)
    
    # Pergerakan arah (Directional Movement)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Pemulusan nilai menggunakan Wilder's EMA
    tr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean()
    
    plus_di = (plus_dm_smooth / tr_smooth.replace(0, np.nan)) * 100
    minus_di = (minus_dm_smooth / tr_smooth.replace(0, np.nan)) * 100
    
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx_series = dx.ewm(alpha=1/period, adjust=False).mean()
    
    return plus_di.fillna(0), minus_di.fillna(0), adx_series.fillna(0)


def calculate_fibonacci(df: pd.DataFrame, lookback: int = 60) -> dict[str, Any]:
    """Menghitung Fibonacci Retracement Levels dari swing high & low dalam lookback window."""
    if len(df) < lookback:
        lookback = len(df)
        
    sub_df = df.tail(lookback)
    high_idx = sub_df["High"].idxmax()
    low_idx = sub_df["Low"].idxmin()
    
    max_high = float(sub_df["High"].loc[high_idx])
    min_low = float(sub_df["Low"].loc[low_idx])
    
    diff = max_high - min_low
    
    # Tentukan tren jangka pendek dalam window ini
    uptrend = high_idx >= low_idx
    
    # Rasio Fibonacci standar
    ratios = [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.000]
    
    levels = {}
    if uptrend:
        # Trend naik: koreksi ditarik ke bawah dari puncak
        for r in ratios:
            levels[f"level_{round(r*100, 1)}"] = round(max_high - r * diff, 2)
    else:
        # Trend turun: retracement ditarik ke atas dari dasar
        for r in ratios:
            levels[f"level_{round(r*100, 1)}"] = round(min_low + r * diff, 2)
            
    # Proyeksi Waktu (Fibonacci Time Cycles)
    # Temukan swing point terakhir
    last_swing_idx = max(high_idx, low_idx)
    last_swing_type = "high" if high_idx >= low_idx else "low"
    
    # Ambil index deret bursa setelah last_swing_idx
    df_after_swing = df.loc[last_swing_idx:]
    
    # Deret Fibonacci waktu: 8, 13, 21, 34, 55, 89
    time_ratios = [8, 13, 21, 34, 55, 89]
    time_cycles = []
    
    # Konversi indeks datetime ke string waktu
    for count in time_ratios:
        projected_date = None
        # Cari tanggal di DataFrame jika ada
        if count < len(df_after_swing):
            projected_date = df_after_swing.index[count]
        else:
            # Proyeksikan manual ke depan menggunakan timedelta sederhana
            # 1 hari bursa approx 1.4 hari kalender
            days_ahead = int(count * 1.4)
            raw_target = last_swing_idx + timedelta(days=days_ahead)
            # Sesuaikan jika akhir pekan
            wd = raw_target.weekday()
            if wd == 5: # Sabtu
                raw_target += timedelta(days=2)
            elif wd == 6: # Minggu
                raw_target += timedelta(days=1)
            projected_date = raw_target
            
        if projected_date:
            try:
                # projected_date can be datetime.date or Timestamp
                p_date = projected_date.date() if hasattr(projected_date, 'date') else projected_date
                days_left = (p_date - datetime.now().date()).days
            except Exception:
                days_left = None
                
            time_cycles.append({
                "cycle": count,
                "date": projected_date.strftime("%Y-%m-%d") if hasattr(projected_date, 'strftime') else str(projected_date),
                "days_left": days_left
            })
            
    return {
        "uptrend_direction": uptrend,
        "max_high": max_high,
        "min_low": min_low,
        "levels": levels,
        "last_swing": {
            "type": last_swing_type,
            "date": last_swing_idx.strftime("%Y-%m-%d") if hasattr(last_swing_idx, 'strftime') else str(last_swing_idx),
        },
        "time_cycles": time_cycles
    }


def _fibonacci_note(price: float, fib: dict) -> str:
    levels = fib["levels"]
    # Temukan level terdekat dengan selisih persen terkecil
    closest_level = None
    min_diff_pct = float("inf")
    
    for lbl, lvl in levels.items():
        diff_pct = abs(lvl - price) / price * 100
        if diff_pct < min_diff_pct:
            min_diff_pct = diff_pct
            closest_level = (lbl, lvl)
            
    if closest_level and min_diff_pct <= 2.0:
        lvl_name = closest_level[0].replace("level_", "")
        return f"Menguji Golden Fibo {lvl_name}% di {closest_level[1]:,.0f} (selisih {min_diff_pct:.1f}%)"
    
    return "Bergerak stabil di antara garis Fibonacci Retracement"


def log_astronacci_cycle(ticker: str, price: float, fib_data: dict[str, Any]) -> None:
    """Mencatat setiap Astronacci Time Cycle sebagai data science untuk analisa prediksi AI."""
    import json
    from app.config import BASE_DIR
    
    log_file = BASE_DIR.parent / "data_store" / "astronacci_cycles.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "ticker": ticker.upper(),
        "price": price,
        "uptrend_direction": fib_data.get("uptrend_direction"),
        "max_high": fib_data.get("max_high"),
        "min_low": fib_data.get("min_low"),
        "last_swing": fib_data.get("last_swing"),
        "time_cycles": fib_data.get("time_cycles")
    }
    
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Support / Resistance                                                       #
# --------------------------------------------------------------------------- #
def _swing_levels(d: pd.DataFrame, window: int) -> tuple[list[float], list[float]]:
    """Titik balik swing (fractal): swing-high = resistance, swing-low = support."""
    highs, lows = d["High"].values, d["Low"].values
    res, sup = [], []
    for i in range(window, len(d) - window):
        if highs[i] == max(highs[i - window:i + window + 1]):
            res.append(float(highs[i]))
        if lows[i] == min(lows[i - window:i + window + 1]):
            sup.append(float(lows[i]))
    return res, sup


def support_resistance(df: pd.DataFrame, lookback: int, window: int) -> tuple[Optional[float], Optional[float]]:
    """Support/Resistance via swing-pivot, dgn fallback bertingkat agar selalu ada acuan.

    1) pivot terdekat di jendela `lookback` (perilaku utama).
    2) bila kosong (harga cetak low/high baru) → pivot dari histori lebih panjang (~4x).
    3) bila masih kosong → low/high ekstrem seluruh histori (lantai/atap sejarah).
    None HANYA bila harga benar-benar di titik ekstrem sepanjang data.
    """
    data = df.tail(lookback)
    if len(data) < window * 2 + 1:
        return None, None
    price = float(data["Close"].iloc[-1])

    res_levels, sup_levels = _swing_levels(data, window)
    resistance = min([r for r in res_levels if r > price], default=None)
    support = max([s for s in sup_levels if s < price], default=None)

    # (2) fallback histori lebih panjang
    if support is None or resistance is None:
        long_res, long_sup = _swing_levels(df.tail(max(lookback * 4, 240)), window)
        if support is None:
            support = max([s for s in long_sup if s < price], default=None)
        if resistance is None:
            resistance = min([r for r in long_res if r > price], default=None)

    # (3) fallback ekstrem sejarah (lantai/atap)
    if support is None:
        lo = float(df["Low"].min())
        support = lo if lo < price else None
    if resistance is None:
        hi = float(df["High"].max())
        resistance = hi if hi > price else None

    return (round(support, 2) if support else None,
            round(resistance, 2) if resistance else None)


def support_resistance_levels(
    df: pd.DataFrame,
    lookback: int,
    window: int,
    max_levels: int = 6,
    tol_pct: float = 1.5,
) -> list[dict[str, Any]]:
    """Beberapa zona Support/Resistance dari swing-pivot yang di-cluster.

    Pivot yang berdekatan (< `tol_pct`) digabung jadi satu zona; makin sering
    sebuah area disentuh makin tinggi `kekuatan`-nya (level lebih valid). Tiap
    zona diklasifikasi relatif harga terakhir: di bawah = support, di atas =
    resistance, lalu diurut dari yang terkuat & terdekat.
    """
    data = df.tail(lookback)
    if len(data) < window * 2 + 1:
        return []
    price = float(data["Close"].iloc[-1])

    res_levels, sup_levels = _swing_levels(data, window)
    pivots = sorted(res_levels + sup_levels)
    if not pivots:
        return []

    clusters: list[list[float]] = [[pivots[0]]]
    for p in pivots[1:]:
        anchor = clusters[-1][0]
        if anchor and abs(p - anchor) / anchor * 100 <= tol_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])

    levels: list[dict[str, Any]] = []
    for cl in clusters:
        lvl = sum(cl) / len(cl)
        levels.append({
            "level": round(lvl, 2),
            "kekuatan": len(cl),
            "jenis": "support" if lvl < price else "resistance",
            "jarak_pct": round((lvl - price) / price * 100, 2),
        })

    levels.sort(key=lambda x: (-x["kekuatan"], abs(x["jarak_pct"])))
    return levels[:max_levels]


# --------------------------------------------------------------------------- #
#  Pola candlestick (candle terakhir)                                         #
# --------------------------------------------------------------------------- #
def detect_candles(df: pd.DataFrame) -> list[str]:
    if len(df) < 3:
        return []
    o, h, l, c = (df[col] for col in ("Open", "High", "Low", "Close"))
    patterns: list[str] = []

    o0, c0, h0, l0 = o.iloc[-1], c.iloc[-1], h.iloc[-1], l.iloc[-1]
    o1, c1 = o.iloc[-2], c.iloc[-2]
    o2, c2 = o.iloc[-3], c.iloc[-3]

    body = abs(c0 - o0)
    rng = (h0 - l0) or 1e-9
    upper = h0 - max(c0, o0)
    lower = min(c0, o0) - l0

    if body <= rng * 0.1:
        patterns.append("Doji")
    if lower >= body * 2 and upper <= body and body > 0:
        patterns.append("Hammer (bullish)" if c0 >= o0 else "Hanging Man")
    if upper >= body * 2 and lower <= body and body > 0:
        patterns.append("Shooting Star (bearish)")

    # Engulfing
    if c1 < o1 and c0 > o0 and c0 >= o1 and o0 <= c1:
        patterns.append("Bullish Engulfing")
    if c1 > o1 and c0 < o0 and o0 >= c1 and c0 <= o1:
        patterns.append("Bearish Engulfing")

    # Harami (body sekarang di dalam body sebelumnya)
    if abs(c1 - o1) > body and max(o0, c0) <= max(o1, c1) and min(o0, c0) >= min(o1, c1):
        patterns.append("Bullish Harami" if c0 > o0 else "Bearish Harami")

    # Morning / Evening star (3 candle)
    if c2 < o2 and abs(c1 - o1) < abs(c2 - o2) * 0.5 and c0 > o0 and c0 > (o2 + c2) / 2:
        patterns.append("Morning Star (bullish)")
    if c2 > o2 and abs(c1 - o1) < abs(c2 - o2) * 0.5 and c0 < o0 and c0 < (o2 + c2) / 2:
        patterns.append("Evening Star (bearish)")

    return patterns


# --------------------------------------------------------------------------- #
#  Volume Profile & Volatility Insight Pro                                    #
# --------------------------------------------------------------------------- #
def calculate_volume_profile(df: pd.DataFrame) -> dict[str, Any]:
    """
    Volume Profile: Membagi rentang harga 60 hari bursa terakhir menjadi 20 bin,
    mengakumulasi volume transaksi, dan menghitung POC, VAH, dan VAL (Value Area 70%).
    """
    lookback = 60
    sub_df = df.tail(lookback) if len(df) >= lookback else df
    
    if sub_df.empty or "Close" not in sub_df.columns or "Volume" not in sub_df.columns:
        return {"poc": None, "vah": None, "val": None, "bins": []}
        
    lows = sub_df["Low"] if "Low" in sub_df.columns else sub_df["Close"]
    highs = sub_df["High"] if "High" in sub_df.columns else sub_df["Close"]
    
    p_min = float(lows.min())
    p_max = float(highs.max())
    
    if p_max <= p_min or np.isnan(p_min) or np.isnan(p_max):
        price = float(sub_df["Close"].iloc[-1]) if not sub_df.empty else 0.0
        return {"poc": price, "vah": price, "val": price, "bins": []}
        
    width = (p_max - p_min) / 20.0
    bins_volume = [0.0] * 20
    
    for _, row in sub_df.iterrows():
        close_val = float(row["Close"])
        vol_val = float(row["Volume"])
        if not np.isnan(close_val) and not np.isnan(vol_val):
            bin_idx = int((close_val - p_min) / width) if width > 0 else 0
            bin_idx = min(19, max(0, bin_idx))
            bins_volume[bin_idx] += vol_val
            
    total_vol = sum(bins_volume)
    max_vol_idx = int(np.argmax(bins_volume))
    poc = p_min + (max_vol_idx + 0.5) * width
    
    if total_vol <= 0:
        return {
            "poc": round(poc, 2),
            "vah": round(p_max, 2),
            "val": round(p_min, 2),
            "bins": [{"price": round(p_min + (i + 0.5) * width, 2), "volume": 0.0} for i in range(20)]
        }
        
    target_vol = total_vol * 0.70
    i_low = max_vol_idx
    i_high = max_vol_idx
    curr_vol = bins_volume[max_vol_idx]
    
    while curr_vol < target_vol and (i_low > 0 or i_high < 19):
        vol_down = bins_volume[i_low - 1] if i_low > 0 else -1.0
        vol_up = bins_volume[i_high + 1] if i_high < 19 else -1.0
        
        if vol_down < 0 and vol_up < 0:
            break
            
        if vol_up >= vol_down:
            i_high += 1
            curr_vol += bins_volume[i_high]
        else:
            i_low -= 1
            curr_vol += bins_volume[i_low]
            
    val = p_min + i_low * width
    vah = p_min + (i_high + 1) * width
    
    bins_list = []
    for i in range(20):
        bins_list.append({
            "price": round(p_min + (i + 0.5) * width, 2),
            "volume": float(bins_volume[i])
        })
        
    return {
        "poc": round(poc, 2),
        "vah": round(vah, 2),
        "val": round(val, 2),
        "bins": bins_list
    }


def calculate_volatility_insight_pro_rating(
    df: pd.DataFrame,
    trend: str,
    s50: Optional[float],
    s200: Optional[float],
    stoch_signal: str,
    patterns: list[str],
    vp_data: dict[str, Any]
) -> dict[str, Any]:
    """
    Volatility Insight Pro: Rating keyakinan multi-faktor (1 s/d 5)
    menilai trend, RSI, volume spike, posisi Volume Profile, dan Stochastic Golden Cross.
    """
    if df.empty or len(df) < 2:
        return {"rating": 1.0, "conviction": "Data tidak mencukupi", "details": []}
        
    close = df["Close"]
    price = float(close.iloc[-1])
    open_now = float(df["Open"].iloc[-1]) if "Open" in df.columns else price
    vol_now = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0.0
    vol_avg = float(df["Volume"].tail(20).mean()) if "Volume" in df.columns and len(df) >= 20 else 0.0
    
    rsi_series = rsi(close, 14)
    rsi_now = float(rsi_series.iloc[-1]) if not rsi_series.empty and not pd.isna(rsi_series.iloc[-1]) else 50.0
    
    val = vp_data.get("val")
    vah = vp_data.get("vah")
    
    factors = []
    total_score = 0.0
    
    # 1. Tren (+1.0)
    trend_score = 0.0
    if s200 is not None and price > s200:
        trend_score += 0.5
        factors.append("Di atas SMA200 (Tren Panjang Bullish) (+0.5)")
    if s50 is not None and price > s50:
        trend_score += 0.5
        factors.append("Di atas SMA50 (Tren Menengah Bullish) (+0.5)")
    total_score += trend_score
    
    # 2. RSI (+1.0)
    if rsi_now < 35:
        total_score += 1.0
        factors.append(f"RSI Oversold ({rsi_now:.1f} < 35) (+1.0)")
    elif 35 <= rsi_now <= 55:
        total_score += 0.5
        factors.append(f"RSI Netral/Bullish ({rsi_now:.1f}) (+0.5)")
    elif rsi_now > 70:
        total_score -= 0.5
        factors.append(f"RSI Overbought ({rsi_now:.1f} > 70) (-0.5)")
        
    # 3. Volume Spike (+1.0)
    if vol_avg > 0 and vol_now > vol_avg * 1.5:
        total_score += 1.0
        ratio = vol_now / vol_avg
        factors.append(f"Volume Spike ({ratio:.1f}x rata-rata 20 hari) (+1.0)")
        
    # 4. Volume Profile Position (+1.0)
    vp_score = 0.0
    if val is not None and vah is not None:
        prev_close = float(close.iloc[-2]) if len(close) >= 2 else price
        
        if prev_close >= val and price < val:
            vp_score = -0.5
            factors.append(f"Breakdown di bawah VAL ({val:,.0f}) (-0.5)")
        elif abs(price - val) / val <= 0.02:
            is_green = (price >= open_now)
            has_golden_cross = stoch_signal.startswith("golden")
            has_bullish_pattern = any("bullish" in p.lower() or "Hammer" in p or "Morning" in p for p in patterns)
            if is_green or has_golden_cross or has_bullish_pattern:
                vp_score = 1.0
                factors.append(f"Pantulan Support di area VAL ({val:,.0f}) (+1.0)")
        elif (prev_close <= vah and price > vah) and (vol_avg > 0 and vol_now > vol_avg * 1.5):
            vp_score = 1.0
            factors.append(f"Breakout Resistance VAH ({vah:,.0f}) + Volume Spike (+1.0)")
            
    total_score += vp_score
    
    # 5. Stochastic Cross (+0.5)
    if stoch_signal.startswith("golden"):
        total_score += 0.5
        factors.append("Stochastic Golden Cross (+0.5)")
        
    final_rating = min(5.0, max(1.0, 1.0 + total_score))
    
    if final_rating >= 4.0:
        conviction = "Tinggi (Strong Conviction)"
    elif final_rating >= 2.5:
        conviction = "Moderat (Neutral-Bullish)"
    else:
        conviction = "Lemah (Speculative / Avoid)"
        
    return {
        "rating": round(final_rating, 1),
        "conviction": conviction,
        "details": factors
    }


# --------------------------------------------------------------------------- #
#  Analisa utama                                                              #
# --------------------------------------------------------------------------- #
def analyze_technical(ticker: str, hist: Optional[pd.DataFrame] = None) -> dict[str, Any]:
    ticker = ticker.upper()
    df = hist if hist is not None else provider.get_history(ticker)
    if df is None or df.empty or len(df) < 30:
        return {"ticker": ticker, "ok": False, "error": "data harga tidak cukup"}

    close = df["Close"]
    price = float(close.iloc[-1])
    sma20 = sma(close, TECH.SMA_FAST)
    sma50 = sma(close, TECH.SMA_SLOW)
    sma200 = sma(close, TECH.SMA_TREND_PERIOD)

    s20 = _last(sma20)
    s50 = _last(sma50)
    s200 = _last(sma200)

    # --- Tren ---
    above_200 = s200 is not None and price > s200
    if above_200 and s20 and s50 and s20 > s50:
        trend = "UPTREND"
    elif s200 is not None and price < s200 and s20 and s50 and s20 < s50:
        trend = "DOWNTREND"
    else:
        trend = "SIDEWAYS"

    # --- Stochastic ---
    k, d = stochastic(df, TECH.STOCH_RSI_PERIOD, TECH.STOCH_K_SMOOTH, TECH.STOCH_D_SMOOTH)
    k_now, d_now = _last(k), _last(d)
    k_prev, d_prev = _prev(k), _prev(d)
    stoch_zone = "netral"
    if k_now is not None:
        if k_now > TECH.STOCH_OVERBOUGHT:
            stoch_zone = "overbought"
        elif k_now < TECH.STOCH_OVERSOLD:
            stoch_zone = "oversold"
    stoch_signal = "—"
    if None not in (k_now, d_now, k_prev, d_prev):
        if k_prev <= d_prev and k_now > d_now:
            stoch_signal = "golden cross (sinyal beli)"
        elif k_prev >= d_prev and k_now < d_now:
            stoch_signal = "dead cross (sinyal jual)"

    # --- Support / Resistance ---
    support, resistance = support_resistance(df, TECH.SR_LOOKBACK, TECH.SR_PIVOT_WINDOW)
    sr_levels = support_resistance_levels(
        df, TECH.SR_LOOKBACK, TECH.SR_PIVOT_WINDOW, TECH.SR_MAX_LEVELS, TECH.SR_CLUSTER_TOL_PCT)
    sr_note = _sr_note(price, support, resistance, sr_levels)

    # --- Volume ---
    vol_avg = float(df["Volume"].tail(TECH.VOLUME_AVG_PERIOD).mean())
    vol_now = float(df["Volume"].iloc[-1])
    vol_spike = vol_now > vol_avg * TECH.VOLUME_SPIKE_MULT if vol_avg else False

    # --- Liquidity Risk ---
    # yfinance volume is in shares. In BEI, 1 lot = 100 shares.
    # volume rata-rata < 500.000 lembar (~5.000 lot/hari) -> Sangat Tinggi (Illiquid)
    # volume rata-rata < 2.000.000 lembar (~20.000 lot/hari) -> Sedang
    # volume rata-rata >= 2.000.000 lembar -> Rendah
    if vol_avg < 500000:
        liquidity_risk = "Sangat Tinggi"
    elif vol_avg < 2000000:
        liquidity_risk = "Sedang"
    else:
        liquidity_risk = "Rendah"

    # --- Candlestick ---
    patterns = detect_candles(df)

    # --- ATR & ADX (Wilder's Smoothing) ---
    atr_series = atr(df, 14)
    atr_val = _last(atr_series)
    atr_pct = (atr_val / price * 100) if atr_val and price else 0
    
    plus_di, minus_di, adx_series = adx(df, 14)
    adx_val = _last(adx_series)
    
    adx_strength = "Lemah (Sideways)"
    adx_class = "down"
    if adx_val is not None:
        if adx_val >= 50:
            adx_strength = "Sangat Kuat"
            adx_class = "up"
        elif adx_val >= 25:
            adx_strength = "Kuat (Trending)"
            adx_class = "up"
        elif adx_val >= 20:
            adx_strength = "Moderat"
            adx_class = ""
        else:
            adx_strength = "Lemah (Sideways)"
            adx_class = "down"

    # --- Sinyal entry (modul hal. 46-49) ---
    signals = _entry_signals(df, price, s50, s200, support, resistance, vol_spike, trend, stoch_signal, stoch_zone)

    bias = _bias(trend, stoch_zone, stoch_signal, signals, patterns)

    # --- Volume Profile & Volatility Insight Pro ---
    vp_data = calculate_volume_profile(df)
    vip_data = calculate_volatility_insight_pro_rating(
        df=df,
        trend=trend,
        s50=s50,
        s200=s200,
        stoch_signal=stoch_signal,
        patterns=patterns,
        vp_data=vp_data
    )

    # --- Fibonacci ---
    fib_data = calculate_fibonacci(df)
    fib_note = _fibonacci_note(price, fib_data)
    log_astronacci_cycle(ticker, price, fib_data)

    return {
        "ticker": ticker,
        "ok": True,
        "price": round(price, 2),
        "trend": trend,
        "volume_profile": vp_data,
        "volatility_insight_pro": vip_data,
        "sma": {"sma20": _r(s20), "sma50": _r(s50), "sma200": _r(s200),
                "price_vs_sma200": "di atas" if above_200 else "di bawah"},
        "stochastic": {"k": _r(k_now), "d": _r(d_now), "zona": stoch_zone, "sinyal": stoch_signal},
        "support": support,
        "resistance": resistance,
        "sr_levels": sr_levels,
        "sr_note": sr_note,
        "volume": {"now": int(vol_now), "avg20": int(vol_avg), "spike": vol_spike, "risk": liquidity_risk},
        "liquidity_risk": liquidity_risk,
        "candlestick": patterns,
        "entry_signals": signals,
        "bias": bias,
        "atr": {
            "value": _r(atr_val),
            "pct": round(atr_pct, 2) if atr_val else None,
            "sl_2atr": round(price - 2 * atr_val, 2) if atr_val and price else None,
            "tp_4atr": round(price + 4 * atr_val, 2) if atr_val and price else None
        },
        "adx": {
            "value": _r(adx_val),
            "strength": adx_strength,
            "class": adx_class,
            "plus_di": _r(_last(plus_di)),
            "minus_di": _r(_last(minus_di))
        },
        "fibonacci": {
            **fib_data,
            "closest_level_note": fib_note
        }
    }


def _entry_signals(df, price, s50, s200, support, resistance, vol_spike, trend, stoch_signal, stoch_zone) -> list[dict]:
    signals: list[dict] = []
    close = df["Close"]
    prev_high_52w = float(df["High"].iloc[-253:-1].max()) if len(df) > 253 else None
    prev_close = float(close.iloc[-2])
    today_open = float(df["Open"].iloc[-1])
    yest_high = float(df["High"].iloc[-2])

    # 52WBO — Breakout 52 Weeks High
    if prev_high_52w and price > prev_high_52w:
        signals.append(_sig("52WBO", "Breakout 52 Weeks High", vol_spike,
                            f"harga {price:.0f} tembus high 52 minggu {prev_high_52w:.0f}"))

    # BOR — Breakout Resistance / Sideways
    if resistance and price > resistance and trend in ("SIDEWAYS", "UPTREND"):
        signals.append(_sig("BOR/FBO", "Breakout Resistance", vol_spike,
                            f"harga {price:.0f} tembus resistance {resistance:.0f}"))

    # BDTL — Breakout Downtrend Line (proxy: tembus SMA50 setelah downtrend)
    if s50 and prev_close < s50 <= price:
        signals.append(_sig("BDTL", "Breakout (tembus SMA50 dari bawah)", vol_spike,
                            f"harga menembus SMA50 {s50:.0f}"))

    # Buy on Pullback — uptrend, harga koreksi mendekati support/SMA20 lalu rebound
    if trend == "UPTREND" and support and price <= support * 1.03 and stoch_signal.startswith("golden"):
        signals.append(_sig("BOP", "Buy on Pullback", True,
                            "uptrend + pullback ke support + golden cross"))

    # Buy on Dips (reversal) — oversold + golden cross
    if stoch_zone == "oversold" and stoch_signal.startswith("golden"):
        signals.append(_sig("BOD", "Buy on Dips (reversal oversold)", vol_spike,
                            "stochastic oversold + golden cross"))

    # Gap Up
    if today_open > yest_high:
        signals.append(_sig("GU", "Gap Up", vol_spike, f"open {today_open:.0f} > high kemarin {yest_high:.0f}"))

    return signals


def _sig(code: str, name: str, with_volume: bool, detail: str) -> dict:
    return {"kode": code, "nama": name, "volume_konfirmasi": with_volume, "detail": detail}


def _bias(trend, stoch_zone, stoch_signal, signals, patterns) -> str:
    bullish_patterns = any("bullish" in p.lower() or "Hammer" in p or "Morning" in p for p in patterns)
    if trend == "UPTREND" and (signals or stoch_signal.startswith("golden") or bullish_patterns):
        return "BULLISH — potensi entry"
    if trend == "DOWNTREND" and stoch_zone != "oversold":
        return "BEARISH — hindari / tunggu"
    if signals:
        return "WATCH — ada sinyal breakout, konfirmasi tren & volume"
    return "NETRAL — belum ada sinyal jelas"


def _sr_note(price, support, resistance, sr_levels) -> str:
    """Narasi singkat posisi harga terhadap zona S/R terdekat (panduan timing)."""
    near = 1.5  # % dianggap "menempel" pada level
    if resistance and abs(resistance - price) / price * 100 <= near:
        return (f"Harga menguji resistance {resistance:.0f} — tunggu breakout + "
                f"volume sebelum entry (hindari beli tepat di atap).")
    if support and abs(support - price) / price * 100 <= near:
        return (f"Harga menempel support {support:.0f} — area pantulan; entry valid "
                f"bila ada konfirmasi reversal, stop di bawah support.")
    strong = [l for l in sr_levels if l["kekuatan"] >= 2]
    if support and resistance:
        extra = f" Zona kuat (≥2 sentuhan): {len(strong)}." if strong else ""
        return (f"Ruang gerak: support {support:.0f} ↓ — resistance {resistance:.0f} ↑."
                f"{extra} Beli dekat support, jual mendekati resistance.")
    if resistance:
        return f"Tak ada support jelas di bawah; resistance terdekat {resistance:.0f}."
    if support:
        return f"Harga di area atas; support terdekat {support:.0f} sebagai jaring pengaman."
    return "Belum ada zona support/resistance signifikan pada rentang ini."


# --------------------------------------------------------------------------- #
#  util                                                                       #
# --------------------------------------------------------------------------- #
def oneill_signal(hist: Optional[pd.DataFrame]) -> dict[str, Any]:
    """Sinyal teknikal ala app lama (RSI+MACD+MA cross) → BUY/HOLD/SELL, score -3..+3."""
    if hist is None or hist.empty or "Close" not in hist or len(hist) < 15:
        return {"signal": "NO DATA", "score": 0, "rsi": None, "ma_cross": None}
    close = hist["Close"].astype(float)
    vol = hist["Volume"].astype(float) if "Volume" in hist else None
    n = len(close)
    reliable, ma50_ok = n >= 35, n >= 50

    rsi_v = rsi(close, 14)
    last_rsi = float(rsi_v.iloc[-1]) if not pd.isna(rsi_v.iloc[-1]) else 50.0
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    hist_line = macd_line - macd_line.ewm(span=9, adjust=False).mean()
    last_h, prev_h = float(hist_line.iloc[-1]), float(hist_line.iloc[-2]) if len(hist_line) > 1 else 0.0
    ma20 = float(sma(close, 20).iloc[-1])
    ma50 = float(sma(close, 50).iloc[-1]) if ma50_ok else None
    last = float(close.iloc[-1])
    ma_cross = ("GOLDEN" if ma20 > ma50 else "DEATH") if ma50_ok else None
    vol_spike = float((vol.iloc[-1] / vol.tail(20).mean())) if (vol is not None and len(vol) >= 20 and vol.tail(20).mean()) else None

    score = 0
    if last_rsi < 30:
        score += 1
    elif last_rsi > 70:
        score -= 1
    if reliable:
        if last_h > 0 and last_h > prev_h:
            score += 1
        elif last_h < 0 and last_h < prev_h:
            score -= 1
    if ma_cross == "GOLDEN" and last > ma20:
        score += 1
    elif ma_cross == "DEATH" and last < ma20:
        score -= 1
    if vol_spike is not None and vol_spike > 1.5 and score >= 0:
        score += 1

    signal = "BUY" if score >= 2 else "SELL" if score <= -2 else "HOLD"
    return {"signal": signal, "score": int(score), "rsi": round(last_rsi, 2),
            "ma_cross": ma_cross, "ma20": round(ma20, 2),
            "ma50": round(ma50, 2) if ma50 else None,
            "volume_spike": round(vol_spike, 2) if vol_spike is not None else None}


def chart_data(ticker: str, hist: Optional[pd.DataFrame] = None, days: int = 400) -> dict[str, Any]:
    """Data OHLCV + indikator untuk grafik candlestick (lightweight-charts)."""
    ticker = ticker.upper()
    df = hist if hist is not None else provider.get_history(ticker)
    if df is None or df.empty:
        return {"ticker": ticker, "ok": False}

    full = df
    sma20 = sma(full["Close"], TECH.SMA_FAST)
    sma50 = sma(full["Close"], TECH.SMA_SLOW)
    sma200 = sma(full["Close"], TECH.SMA_TREND_PERIOD)
    k, d = stochastic(full, TECH.STOCH_RSI_PERIOD, TECH.STOCH_K_SMOOTH, TECH.STOCH_D_SMOOTH)

    tail = full.tail(days)

    def _t(idx) -> str:
        return idx.strftime("%Y-%m-%d")

    candles, volume, line20, line50, line200, kline, dline = [], [], [], [], [], [], []
    for idx, row in tail.iterrows():
        t = _t(idx)
        o, h, l, c, v = (float(row["Open"]), float(row["High"]), float(row["Low"]),
                         float(row["Close"]), float(row["Volume"]))
        candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
        volume.append({"time": t, "value": v, "color": "#16c78455" if c >= o else "#ea394355"})
        for line, series in ((line20, sma20), (line50, sma50), (line200, sma200),
                             (kline, k), (dline, d)):
            val = series.get(idx)
            if val is not None and not pd.isna(val):
                line.append({"time": t, "value": round(float(val), 2)})

    support, resistance = support_resistance(full, TECH.SR_LOOKBACK, TECH.SR_PIVOT_WINDOW)
    sr_levels = support_resistance_levels(
        full, TECH.SR_LOOKBACK, TECH.SR_PIVOT_WINDOW, TECH.SR_MAX_LEVELS, TECH.SR_CLUSTER_TOL_PCT)

    # Ambil data valuasi fundamental (Harga Wajar & BVPS)
    graham_number = None
    bvps = None
    try:
        from app.core import undervalue
        from app.data import master_data
        uv = undervalue.evaluate(ticker)
        if uv:
            val_extra = uv.get("valuation_extra", {})
            graham_number = val_extra.get("graham_number")
        
        metrics = master_data.metrics(ticker)
        if metrics:
            bvps = metrics.get("bvps")
    except Exception:
        pass

    return {
        "ticker": ticker, "ok": True,
        "candles": candles, "volume": volume,
        "sma20": line20, "sma50": line50, "sma200": line200,
        "stoch_k": kline, "stoch_d": dline,
        "support": support, "resistance": resistance,
        "sr_levels": sr_levels,
        "graham_number": graham_number,
        "bvps": bvps,
    }


def _last(s: pd.Series) -> Optional[float]:
    if s is None or s.empty or pd.isna(s.iloc[-1]):
        return None
    return float(s.iloc[-1])


def _prev(s: pd.Series) -> Optional[float]:
    if s is None or len(s) < 2 or pd.isna(s.iloc[-2]):
        return None
    return float(s.iloc[-2])


def _r(v: Optional[float]) -> Optional[float]:
    return round(v, 2) if v is not None else None
