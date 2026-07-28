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
        feats = feats.dropna(subset=["rsi14", "close_sma200"])  # rolling belum penuh
        if feats.empty:
            continue
        feats = feats.reset_index().rename(columns={"Date": "date", "index": "date"})
        feats.insert(0, "ticker", tk)
        frames.append(feats)

    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True)


def main() -> None:
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


if __name__ == "__main__":
    main()
