"""
Kolektor universe penuh IDX untuk datalake — melampaui 75 saham terkurasi.

Tujuan (keputusan 2026-07-28): datalake yang mumpuni butuh cakupan luas dan
bebas survivorship bias KE DEPAN:
  1. Daftar SEMUA ticker saham IDX dari scanner TradingView (fallback:
     union CSV lokal). Universe TRADING tetap 75 terkurasi — daftar penuh
     ini murni untuk koleksi DATA.
  2. Snapshot keanggotaan harian -> ml_data/universe_snapshots/ (arsip
     point-in-time; kelak menjawab "saham apa saja yang ADA pada tanggal X").
  3. Fetch OHLCV harian universe penuh ke ml_data/history/ (incremental,
     cache 20 jam) -> tersinkron ke NAS raw/prices.

CLI:
    python -m app.ml.universe_collector --list       # cetak ukuran universe
    python -m app.ml.universe_collector --snapshot   # simpan snapshot harian
    python -m app.ml.universe_collector --fetch      # snapshot + fetch OHLCV
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import BASE_DIR
from app.ml.data_fetch import ML_DATA_DIR, fetch_and_store

SNAPSHOT_DIR = ML_DATA_DIR / "universe_snapshots"
WIB = ZoneInfo("Asia/Jakarta")

SCANNER_URL = "https://scanner.tradingview.com/indonesia/scan"


def _from_tradingview() -> list[dict]:
    """Semua saham IDX dari scanner TradingView (nama + sektor ikut)."""
    import httpx
    payload = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "columns": ["name", "description", "sector", "close", "market_cap_basic"],
        "range": [0, 2000],
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.post(SCANNER_URL, json=payload)
        r.raise_for_status()
        data = r.json()
    rows = []
    for item in data.get("data", []):
        d = item.get("d") or []
        tk = (d[0] or "").strip().upper() if d else ""
        if not tk or not tk.isalpha() or len(tk) > 6:
            continue
        rows.append({"ticker": tk, "name": d[1] if len(d) > 1 else "",
                     "sector": d[2] if len(d) > 2 else "",
                     "close": d[3] if len(d) > 3 else None,
                     "market_cap": d[4] if len(d) > 4 else None})
    return rows


def _from_local_csv() -> list[dict]:
    """Fallback: union daftar lokal (terkurasi + sharia_universe)."""
    seen, rows = set(), []
    for fname in ("master_data_syariah.csv", "sharia_universe.csv",
                  "daftar_saham_syariah.csv"):
        path = BASE_DIR / "data" / fname
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tk = (row.get("Ticker") or row.get("ticker") or "").strip().upper()
                if tk and tk not in seen:
                    seen.add(tk)
                    rows.append({"ticker": tk,
                                 "name": row.get("Nama Perusahaan") or row.get("name") or "",
                                 "sector": row.get("Sektor") or row.get("sector") or ""})
    return rows


def full_universe() -> tuple[list[dict], str]:
    """(daftar ticker IDX, sumber). Scanner dulu; fallback CSV lokal."""
    try:
        rows = _from_tradingview()
        if len(rows) >= 300:                     # sanity: IDX ~900 emiten
            return rows, "tradingview_scanner"
    except Exception:
        pass
    return _from_local_csv(), "local_csv_fallback"


def save_snapshot() -> Path:
    """Snapshot keanggotaan universe hari ini (point-in-time, append-only)."""
    rows, source = full_universe()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(WIB).date().isoformat()
    path = SNAPSHOT_DIR / f"idx_universe_{today}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "name", "sector",
                                          "close", "market_cap"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
    meta = {"date": today, "source": source, "count": len(rows),
            "saved_at": datetime.now(WIB).isoformat(timespec="seconds")}
    (SNAPSHOT_DIR / f"idx_universe_{today}.meta.json").write_text(
        json.dumps(meta, indent=1))
    return path


def fetch_full_history(max_age_hours: float = 20.0) -> dict:
    """Fetch OHLCV universe penuh (incremental — hanya yang basi)."""
    rows, source = full_universe()
    tickers = [r["ticker"] for r in rows]
    summary = fetch_and_store(tickers=tickers, max_age_hours=max_age_hours,
                              sleep_s=0.4)
    ok = sum(1 for s in summary.values() if "error" not in s)
    return {"source": source, "total": len(tickers), "ok": ok,
            "failed": len(tickers) - ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    if args.list:
        rows, source = full_universe()
        print(f"{len(rows)} ticker (sumber: {source})")
    if args.snapshot or args.fetch:
        path = save_snapshot()
        print(f"Snapshot: {path}")
    if args.fetch:
        res = fetch_full_history()
        print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
