"""
Perakitan dataset panel (ticker x tanggal) untuk training model sinyal.

Output: ml_data/dataset.parquet — kolom fitur (FEATURE_COLUMNS) + label
fwd_ret_{N}/label_{N} + kolom identitas (ticker, date).

CLI:
    python -m app.ml.dataset            # rakit dataset dari parquet history
"""

from __future__ import annotations

import pandas as pd

from app.ml import data_fetch
from app.ml.features import build_features, add_labels

# Mulai 2015: kualitas data era sebelumnya buruk (banyak split tak tercatat).
DATASET_START = "2015-01-01"

# Ticker tanpa data layak (mis. suspensi panjang) — dikecualikan dari training.
EXCLUDE = {"WSKT"}

DATASET_PATH = data_fetch.ML_DATA_DIR / "dataset.parquet"

# Likuiditas minimum: median turnover 20 hari (Rp) agar sinyal bisa dieksekusi.
MIN_TURNOVER = 1e9

# Harga minimum (Rp) — saham di bawah ini dikecualikan dari training & sinyal:
# tick size relatif besar => slippage riil menggerus edge (keputusan 2026-07-28).
MIN_PRICE = 200.0


def build_dataset(min_bars: int = 300) -> pd.DataFrame:
    market = data_fetch.load_history(data_fetch.INDEX_TICKER)
    if market.empty:
        raise RuntimeError("History IHSG belum ada — jalankan app.ml.data_fetch dulu")

    frames = []
    for tk in data_fetch._idx_universe():
        if tk in EXCLUDE:
            continue
        df = data_fetch.load_history(tk)
        if len(df) < min_bars:
            continue
        feats = build_features(df, market)
        feats = add_labels(feats, df)
        feats = feats.loc[feats.index >= DATASET_START]
        # Saring hari tidak likuid (volume 0 / turnover kecil): sinyal
        # di hari seperti itu tidak bisa dieksekusi dengan wajar.
        turnover = (df["Close"] * df["Volume"]).rolling(20).median()
        feats = feats[turnover.reindex(feats.index) >= MIN_TURNOVER]
        # Filter harga point-in-time: harga PADA TANGGAL itu >= MIN_PRICE
        close_at = df["Close"].reindex(feats.index)
        feats = feats[close_at >= MIN_PRICE]
        feats = feats.dropna(subset=["rsi14", "close_sma200"])  # rolling belum penuh
        if feats.empty:
            continue
        feats["price"] = df["Close"].reindex(feats.index)
        feats = feats.reset_index().rename(columns={"Date": "date", "index": "date"})
        feats.insert(0, "ticker", tk)
        frames.append(feats)

    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    from app.ml.features import add_cross_sectional_ranks
    panel = add_cross_sectional_ranks(panel)
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True)


SCREENED_PATH = data_fetch.ML_DATA_DIR / "dataset_screened.parquet"


def apply_conventional_screen(panel: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
    """Emulasi screening konvensional secara HISTORIS (point-in-time).

    Meniru gerbang funnel yang bisa dihitung dari harga (fundamental
    point-in-time belum tersedia — mulai terkumpul di datalake):
      1. Uptrend: close > SMA200 dan SMA50 > SMA200 (filter tren funnel).
      2. Momentum tidak overbought ekstrem: RSI14 < 75.
      3. Likuiditas sudah disaring saat build_dataset (turnover >= Rp1M).
      4. Ambil top-K per tanggal berdasar skor konvensional: relative
         strength 60d vs IHSG + momentum 20d + aktivitas volume.

    Hasil: populasi training = "10 saham paling prospektif versi metoda
    konvensional" per hari — selaras dengan populasi tempat model dipakai.
    """
    df = panel.copy()
    mask = (df["close_sma200"] > 0) & (df["sma50_sma200"] > 0) & (df["rsi14"] < 75)
    df = df[mask]
    if df.empty:
        return df

    def _z(s: pd.Series) -> pd.Series:
        sd = s.std()
        return (s - s.mean()) / sd if sd and sd > 0 else s * 0.0

    def _per_day(g: pd.DataFrame) -> pd.DataFrame:
        score = _z(g["rs_60"].fillna(0)) + _z(g["ret_20"].fillna(0)) \
            + 0.5 * _z(g["vol_ratio20"].fillna(1))
        g = g.assign(conv_score=score)
        return g.nlargest(top_k, "conv_score")

    out = df.groupby("date", group_keys=False).apply(_per_day)
    return out.reset_index(drop=True)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--screened", action="store_true",
                    help="juga bangun dataset screening konvensional top-10/hari")
    args = ap.parse_args()
    panel = build_dataset()
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(DATASET_PATH)
    n_tickers = panel["ticker"].nunique()
    print(f"Dataset: {len(panel):,} baris, {n_tickers} ticker, "
          f"{panel['date'].min().date()} -> {panel['date'].max().date()}")
    for n in (5, 10, 20):
        lab = panel[f"label_{n}"].dropna()
        dist = lab.value_counts(normalize=True).sort_index().round(3).to_dict()
        print(f"  label_{n}: n={len(lab):,} dist={dist}")
    print(f"Tersimpan: {DATASET_PATH}")
    if args.screened:
        scr = apply_conventional_screen(panel)
        scr.to_parquet(SCREENED_PATH)
        print(f"Screened: {len(scr):,} baris ({scr['ticker'].nunique()} ticker) "
              f"-> {SCREENED_PATH}")


if __name__ == "__main__":
    main()
