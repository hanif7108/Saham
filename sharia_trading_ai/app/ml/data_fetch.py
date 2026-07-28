"""
Fetch & simpan data historis OHLCV untuk training model ML sinyal.

Sumber: yfinance dengan auto_adjust=False (harga cocok broker/TradingView),
plus kolom Adj Close untuk menghitung return yang benar terhadap
split/dividend. Data disimpan per ticker sebagai parquet di ML_DATA_DIR.

CLI:
    python -m app.ml.data_fetch            # fetch semua ticker universe IDX
    python -m app.ml.data_fetch --audit    # fetch + cetak laporan audit kualitas
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Optional

import pandas as pd

from app.config import BASE_DIR

ML_DATA_DIR = BASE_DIR.parent / "ml_data"
HISTORY_DIR = ML_DATA_DIR / "history"

INDEX_TICKER = "^JKSE"


def _idx_universe() -> list[str]:
    """Ticker IDX dari master_data_syariah.csv (tanpa universe AS)."""
    from app.data.provider import get_universe, is_us_ticker
    return [row["ticker"] for row in get_universe()
            if not is_us_ticker(row["ticker"])]


def fetch_history_full(ticker: str, period: str = "max") -> pd.DataFrame:
    """OHLCV harian penuh + Adj Close + Dividends/Stock Splits dari yfinance."""
    from app.data.provider import _ticker, to_yahoo
    yft = _ticker(to_yahoo(ticker))
    df = yft.history(period=period, interval="1d",
                     auto_adjust=False, actions=True)
    if df is None or df.empty:
        return pd.DataFrame()
    keep = [c for c in ("Open", "High", "Low", "Close", "Adj Close",
                        "Volume", "Dividends", "Stock Splits") if c in df.columns]
    df = df[keep].dropna(subset=["Close"])
    # Index tz-aware (Asia/Jakarta) -> normalisasi ke date naive agar join antar
    # ticker konsisten.
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "Date"
    return df


def history_path(ticker: str) -> Path:
    safe = ticker.replace("^", "_idx_").replace(".", "_")
    return HISTORY_DIR / f"{safe}.parquet"


def load_history(ticker: str) -> pd.DataFrame:
    path = history_path(ticker)
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def fetch_and_store(tickers: Optional[list[str]] = None,
                    max_age_hours: float = 20.0,
                    sleep_s: float = 0.6) -> dict[str, dict]:
    """Fetch semua ticker + IHSG, simpan parquet. Return ringkasan per ticker.

    File yang masih lebih muda dari max_age_hours dilewati (agar retrain
    harian/bulanan tidak memukul Yahoo untuk data yang sama).
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if tickers is None:
        tickers = _idx_universe() + [INDEX_TICKER]

    summary: dict[str, dict] = {}
    for i, tk in enumerate(tickers):
        path = history_path(tk)
        if path.exists() and (time.time() - path.stat().st_mtime) < max_age_hours * 3600:
            df = pd.read_parquet(path)
            summary[tk] = _summarize(tk, df, cached=True)
            continue
        try:
            df = fetch_history_full(tk)
        except Exception as e:  # jaringan/rate-limit: catat, lanjut
            summary[tk] = {"ticker": tk, "error": str(e)[:200]}
            time.sleep(sleep_s)
            continue
        if df.empty:
            summary[tk] = {"ticker": tk, "error": "empty"}
        else:
            df.to_parquet(path)
            summary[tk] = _summarize(tk, df, cached=False)
        time.sleep(sleep_s)
    return summary


def _summarize(ticker: str, df: pd.DataFrame, cached: bool) -> dict:
    if df.empty:
        return {"ticker": ticker, "error": "empty"}
    idx = pd.to_datetime(df.index)
    bdays = pd.bdate_range(idx.min(), idx.max())
    # gap = hari bursa (Sen-Jum) tanpa bar; libur BEI ikut terhitung, jadi
    # angka kecil (~15-20/tahun) itu normal — yang dicari gap ekstrem.
    missing = len(bdays.difference(idx))
    zero_vol = int((df["Volume"] == 0).sum())
    splits = df["Stock Splits"][df["Stock Splits"] != 0] if "Stock Splits" in df else pd.Series(dtype=float)
    ret = df["Close"].pct_change().abs()
    extreme_moves = int((ret > 0.35).sum())  # loncatan >35% -> indikasi split tak ter-adjust
    return {
        "ticker": ticker,
        "start": str(idx.min().date()),
        "end": str(idx.max().date()),
        "rows": int(len(df)),
        "years": round((idx.max() - idx.min()).days / 365.25, 1),
        "missing_bdays": missing,
        "missing_pct": round(100 * missing / max(len(bdays), 1), 1),
        "zero_volume_days": zero_vol,
        "n_splits": int(len(splits)),
        "extreme_moves_gt35pct": extreme_moves,
        "cached": cached,
    }


def audit_report(summary: dict[str, dict]) -> str:
    rows = [s for s in summary.values() if "error" not in s]
    errs = [s for s in summary.values() if "error" in s]
    df = pd.DataFrame(rows).sort_values("years")
    lines = [
        f"Ticker OK: {len(rows)}   gagal/kosong: {len(errs)}",
        f"Median histori: {df['years'].median():.1f} tahun; "
        f"min {df['years'].min():.1f} ({df.iloc[0]['ticker']}), "
        f"max {df['years'].max():.1f}",
        f"Ticker dengan histori < 5 tahun: "
        f"{', '.join(df[df['years'] < 5]['ticker'].tolist()) or '-'}",
        f"Ticker dengan gap hari bursa > 10%: "
        f"{', '.join(df[df['missing_pct'] > 10]['ticker'].tolist()) or '-'}",
        f"Ticker dengan lompatan harga >35% (cek split): "
        f"{', '.join(df[df['extreme_moves_gt35pct'] > 0]['ticker'].tolist()) or '-'}",
    ]
    if errs:
        lines.append("Gagal: " + ", ".join(s["ticker"] for s in errs))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="cetak laporan audit")
    ap.add_argument("--force", action="store_true", help="abaikan cache parquet")
    args = ap.parse_args()

    summary = fetch_and_store(max_age_hours=0 if args.force else 20.0)
    out = ML_DATA_DIR / "audit_summary.json"
    out.write_text(json.dumps(summary, indent=1))
    print(f"Ringkasan tersimpan: {out}")
    if args.audit:
        print(audit_report(summary))


if __name__ == "__main__":
    main()
