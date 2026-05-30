"""
Technical Analysis Module
=========================
Indikator: RSI, MACD, SMA/EMA, Bollinger Bands, Volume Spike.
Generate sinyal beli/jual berdasarkan kombinasi indikator.

Tidak bergantung pada library teknikal eksternal (TA-Lib) — implementasi murni pandas/numpy
agar mudah dideploy di mana saja.
"""

import numpy as np
import pandas as pd


# ----------------------------- INDICATORS ----------------------------- #

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=1).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    # Wilder smoothing pakai EMA dengan alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_value = 100 - (100 / (1 + rs))
    return rsi_value.fillna(50)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, Signal line, Histogram."""
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({
        "MACD": macd_line,
        "Signal": signal_line,
        "Histogram": histogram
    })


def bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands (Upper, Middle, Lower)."""
    mid = sma(series, period)
    std = series.rolling(window=period, min_periods=1).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return pd.DataFrame({"BB_Upper": upper, "BB_Middle": mid, "BB_Lower": lower})


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """Rasio volume hari ini terhadap rata-rata 20 hari."""
    avg = volume.rolling(window=period, min_periods=1).mean()
    return volume / avg.replace(0, np.nan)


# ----------------------------- SIGNALS ----------------------------- #

def compute_signals(df: pd.DataFrame) -> dict:
    """
    Hitung semua indikator dan buat sinyal akhir.

    Input:
        df : DataFrame dengan kolom 'Close' (wajib) dan opsional 'Volume'.
             Index sebaiknya berurutan secara tanggal.

    Output:
        dict dengan ringkasan indikator + sinyal:
            - rsi, macd_hist, ma20, ma50, ma_cross, volume_spike
            - signal: BUY / SELL / HOLD
            - score: -3..+3 (ringkasan kekuatan teknikal)
            - reasons: list narasi alasan
    """
    if df is None or df.empty or "Close" not in df.columns:
        return {
            "signal": "NO DATA", "score": 0, "rsi": None,
            "macd_hist": None, "ma_cross": None, "volume_spike": None,
            "reasons": ["Data harga tidak tersedia"]
        }

    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else None

    # Hitung indikator
    rsi_series = rsi(close, 14)
    macd_df = macd(close)
    ma20 = sma(close, 20)
    ma50 = sma(close, 50)

    last_rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else 50.0
    last_hist = float(macd_df["Histogram"].iloc[-1]) if not macd_df.empty else 0.0
    prev_hist = float(macd_df["Histogram"].iloc[-2]) if len(macd_df) > 1 else 0.0
    last_ma20 = float(ma20.iloc[-1]) if not ma20.empty else float(close.iloc[-1])
    last_ma50 = float(ma50.iloc[-1]) if not ma50.empty else float(close.iloc[-1])
    last_close = float(close.iloc[-1])

    # MA Cross status
    ma_cross = "GOLDEN" if last_ma20 > last_ma50 else "DEATH"

    # Volume spike
    vol_spike = None
    if volume is not None and len(volume) >= 20:
        vr = volume_ratio(volume, 20)
        vol_spike = float(vr.iloc[-1])

    # Scoring teknikal (-3..+3)
    score = 0
    reasons = []

    # RSI
    if last_rsi < 30:
        score += 1
        reasons.append(f"RSI oversold ({last_rsi:.1f}) → potensi rebound")
    elif last_rsi > 70:
        score -= 1
        reasons.append(f"RSI overbought ({last_rsi:.1f}) → potensi koreksi")
    else:
        reasons.append(f"RSI netral ({last_rsi:.1f})")

    # MACD histogram
    if last_hist > 0 and last_hist > prev_hist:
        score += 1
        reasons.append("MACD histogram positif & menguat")
    elif last_hist < 0 and last_hist < prev_hist:
        score -= 1
        reasons.append("MACD histogram negatif & melemah")

    # MA Cross + posisi harga
    if ma_cross == "GOLDEN" and last_close > last_ma20:
        score += 1
        reasons.append("Golden cross & harga di atas MA20")
    elif ma_cross == "DEATH" and last_close < last_ma20:
        score -= 1
        reasons.append("Death cross & harga di bawah MA20")

    # Volume spike (bonus)
    if vol_spike is not None and vol_spike > 1.5 and score >= 0:
        score += 1
        reasons.append(f"Volume spike {vol_spike:.1f}x → konfirmasi minat")

    # Tentukan sinyal akhir
    if score >= 2:
        signal = "BUY"
    elif score <= -2:
        signal = "SELL"
    else:
        signal = "HOLD"

    # Jalur 7% evaluation
    from .jalur_7 import evaluate_jalur7
    jalur7_eval = evaluate_jalur7(df)

    return {
        "signal": signal,
        "score": int(score),
        "rsi": round(last_rsi, 2),
        "macd_hist": round(last_hist, 4),
        "ma20": round(last_ma20, 2),
        "ma50": round(last_ma50, 2),
        "ma_cross": ma_cross,
        "volume_spike": round(vol_spike, 2) if vol_spike is not None else None,
        "last_close": round(last_close, 2),
        "reasons": reasons,
        "jalur7": jalur7_eval
    }


def chart_payload(df: pd.DataFrame, lookback: int = 90) -> dict:
    """
    Siapkan data untuk frontend chart (Chart.js).
    Return dict yang JSON-serializable: tanggal, OHLC, MA20, MA50, RSI, MACD.
    """
    if df is None or df.empty:
        return {"labels": [], "close": [], "ma20": [], "ma50": [], "rsi": [], "macd_hist": []}

    df = df.tail(lookback).copy()
    close = df["Close"].astype(float)

    return {
        "labels": [str(idx.date()) if hasattr(idx, "date") else str(idx) for idx in df.index],
        "close": close.round(2).tolist(),
        "ma20": sma(close, 20).round(2).tolist(),
        "ma50": sma(close, 50).round(2).tolist(),
        "rsi": rsi(close, 14).round(2).tolist(),
        "macd_hist": macd(close)["Histogram"].round(4).tolist(),
        "volume": df["Volume"].astype(float).tolist() if "Volume" in df.columns else []
    }


if __name__ == "__main__":
    # Quick smoke test pakai random walk
    np.random.seed(42)
    n = 120
    prices = 1000 + np.cumsum(np.random.randn(n) * 10)
    vols = np.random.randint(500_000, 5_000_000, n)
    test_df = pd.DataFrame({
        "Close": prices,
        "Volume": vols
    }, index=pd.date_range("2024-01-01", periods=n))

    result = compute_signals(test_df)
    print("=== SMOKE TEST technical_analysis.py ===")
    for k, v in result.items():
        print(f"  {k}: {v}")
