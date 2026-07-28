"""
Feature engineering untuk model ML sinyal — vectorized per ticker.

Prinsip:
- Semua fitur point-in-time: hanya memakai data s/d bar t (tanpa look-ahead).
- Fitur dihitung dari Close mentah (split-adjusted, non-dividend-adjusted)
  agar identik dengan data runtime provider.get_history().
- Label forward return memakai Adj Close (total return, benar terhadap
  split + dividend) — hanya tersedia saat training.

Fitur meniru sinyal pipeline rule-based: RSI/MA cross (technical_analysis),
breakout & volume (jalur_7), relative strength vs IHSG (CAN SLIM huruf L/S),
regime pasar (layered_scoring).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Kolom fitur, urutan tetap = kontrak dengan artifact model.
FEATURE_COLUMNS = [
    "ret_1", "ret_5", "ret_10", "ret_20", "ret_60",
    "rsi14",
    "close_sma20", "close_sma50", "close_sma200", "sma50_sma200",
    "ma_cross_up",
    "vol_ratio20", "vol_z20", "turnover_log",
    "atr14_pct", "std20",
    "stoch_k", "stoch_d",
    "dist_high52w", "dist_low52w",
    "breakout20", "breakout60",
    "body_pct", "range_pct", "gap_pct",
    "rs_20", "rs_60",
    "mkt_close_sma200", "mkt_ret_20",
    "dow", "month",
]

# Fitur peringkat lintas-saham (persentil antar ticker pada tanggal sama).
# Dipakai model ranking; dihitung per tanggal di dataset & per scan di runtime.
CS_RANK_BASE = ["ret_5", "ret_20", "rs_20", "rs_60", "vol_ratio20",
                "atr14_pct", "dist_high52w", "turnover_log"]
CS_RANK_COLUMNS = [f"csr_{c}" for c in CS_RANK_BASE]
RANK_MODEL_FEATURES = FEATURE_COLUMNS + CS_RANK_COLUMNS


def add_cross_sectional_ranks(panel):
    """Tambah kolom csr_* = persentil fitur antar ticker per tanggal."""
    out = panel.copy()
    for c in CS_RANK_BASE:
        out[f"csr_{c}"] = out.groupby("date")[c].rank(pct=True)
    return out


LABEL_HORIZONS = (5, 10, 20)

# Ambang klasifikasi BUY/SELL per horizon (forward return).
LABEL_THRESHOLDS = {5: 0.02, 10: 0.03, 20: 0.05}

# |return harian| di atas ini dianggap anomali data (split tak tercatat, dsb.)
ANOMALY_DAILY_RET = 0.30


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _stoch(df: pd.DataFrame, period: int = 14, smooth: int = 3) -> tuple[pd.Series, pd.Series]:
    lo = df["Low"].rolling(period).min()
    hi = df["High"].rolling(period).max()
    k = 100 * (df["Close"] - lo) / (hi - lo).replace(0, np.nan)
    k = k.rolling(smooth).mean()
    d = k.rolling(smooth).mean()
    return k, d


def build_features(df: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """Feature matrix dari OHLCV satu ticker + OHLCV indeks (IHSG).

    df & market: kolom Open/High/Low/Close/Volume, index tanggal harian.
    Baris awal (rolling window belum penuh) menghasilkan NaN — biarkan,
    pemanggil yang memutuskan dropna (training) atau ambil bar terakhir
    (runtime, setelah minimal ~260 bar).
    """
    c = df["Close"]
    out = pd.DataFrame(index=df.index)

    for n in (1, 5, 10, 20, 60):
        out[f"ret_{n}"] = c.pct_change(n)

    out["rsi14"] = _rsi(c)

    sma20, sma50, sma200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    out["close_sma20"] = c / sma20 - 1
    out["close_sma50"] = c / sma50 - 1
    out["close_sma200"] = c / sma200 - 1
    out["sma50_sma200"] = sma50 / sma200 - 1
    cross = (sma50 > sma200).astype(float)
    out["ma_cross_up"] = (cross.diff() > 0).astype(float)

    vol = df["Volume"].astype(float)
    vol_ma20 = vol.rolling(20).mean()
    out["vol_ratio20"] = vol / vol_ma20.replace(0, np.nan)
    out["vol_z20"] = (vol - vol_ma20) / vol.rolling(20).std().replace(0, np.nan)
    out["turnover_log"] = np.log1p(c * vol)

    out["atr14_pct"] = _atr(df) / c
    out["std20"] = c.pct_change().rolling(20).std()

    k, d = _stoch(df)
    out["stoch_k"], out["stoch_d"] = k, d

    hi52 = c.rolling(252).max()
    lo52 = c.rolling(252).min()
    out["dist_high52w"] = c / hi52 - 1
    out["dist_low52w"] = c / lo52 - 1

    # Breakout ala jalur_7: close menembus high N-hari sebelumnya.
    out["breakout20"] = (c > c.shift(1).rolling(20).max()).astype(float)
    out["breakout60"] = (c > c.shift(1).rolling(60).max()).astype(float)

    o, h, l = df["Open"], df["High"], df["Low"]
    out["body_pct"] = (c - o) / o.replace(0, np.nan)
    out["range_pct"] = (h - l) / c
    out["gap_pct"] = o / c.shift(1) - 1

    # Relative strength vs IHSG (proxy huruf L CAN SLIM).
    mkt_c = market["Close"].reindex(df.index).ffill()
    for n in (20, 60):
        out[f"rs_{n}"] = c.pct_change(n) - mkt_c.pct_change(n)
    out["mkt_close_sma200"] = mkt_c / mkt_c.rolling(200).mean() - 1
    out["mkt_ret_20"] = mkt_c.pct_change(20)

    out["dow"] = df.index.dayofweek.astype(float)
    out["month"] = df.index.month.astype(float)

    return out[FEATURE_COLUMNS]


def add_labels(features: pd.DataFrame, df: pd.DataFrame,
               horizons: tuple[int, ...] = LABEL_HORIZONS) -> pd.DataFrame:
    """Tambah kolom fwd_ret_{N} & label_{N} (1=BUY, 0=HOLD, -1=SELL).

    Return dihitung dari Adj Close (total return). Baris yang jendela
    forward-nya mengandung anomali harga (|ret harian| > ANOMALY_DAILY_RET)
    diberi NaN agar tidak meracuni training.
    """
    adj = df["Adj Close"] if "Adj Close" in df.columns else df["Close"]
    daily = adj.pct_change()
    anomaly = daily.abs() > ANOMALY_DAILY_RET

    out = features.copy()
    for n in horizons:
        fwd = adj.shift(-n) / adj - 1
        # jendela forward [t+1, t+n] mengandung anomali? (dihitung mundur)
        bad_fwd = (anomaly.iloc[::-1].rolling(n, min_periods=1).sum().iloc[::-1]
                   .shift(-1).fillna(0) > 0)
        # anomali pada bar t sendiri juga membatalkan sampel
        bad = bad_fwd | anomaly.fillna(False)
        thr = LABEL_THRESHOLDS[n]
        out[f"fwd_ret_{n}"] = fwd.where(~bad)
        label = pd.Series(0, index=out.index, dtype=float)
        label[fwd > thr] = 1
        label[fwd < -thr] = -1
        out[f"label_{n}"] = label.where(~bad & fwd.notna())
    return out
