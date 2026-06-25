"""
Rebuild master_data_syariah.csv dari yfinance (port build_master_data.py app lama).

Mengisi 6 Magic Numbers + Free Float + Dividend Yield per saham DES, agar
fundamental tidak basi (data terkurasi yang dipakai screening & rekomendasi).
Sumber utama: yfinance `info`. Kolom & format dijaga kompatibel dgn master_data.py.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any, Optional

from app.config import DATA_DIR
from app.data import provider

MASTER_CSV = DATA_DIR / "master_data_syariah.csv"
DES_CSV = DATA_DIR / "daftar_saham_syariah.csv"
STATUS = DATA_DIR.parent.parent / "data_store" / "master_status.json"
STATUS.parent.mkdir(parents=True, exist_ok=True)

COLUMNS = ["Ticker", "Nama Perusahaan", "Sektor", "EPS QnQ", "ROA", "ROE", "NPM",
           "PER", "PBV", "DER", "PEG", "BVPS", "MP", "Free Float", "Dividend Yield", "Source"]


def _pct(v, factor=100) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v) * factor:.2f}%"
    except Exception:
        return "N/A"


def _pct_smart(v) -> str:
    """Dividend yield/DER: yfinance kadang desimal (0.092) kadang persen (9.2)."""
    if v is None:
        return "N/A"
    try:
        x = float(v)
        return f"{(x if abs(x) > 1.5 else x * 100):.2f}%"
    except Exception:
        return "N/A"


def _x(v, max_realistic=1000) -> str:
    if v is None:
        return "N/A"
    try:
        x = float(v)
        return "N/A" if abs(x) > max_realistic else f"{x:.2f}x"
    except Exception:
        return "N/A"


def _num(v) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2f}"
    except Exception:
        return "N/A"


def _ticker_list() -> list[str]:
    """Daftar saham target: dari DES list, fallback ke master existing/universe."""
    for path in (DES_CSV, MASTER_CSV):
        if path.exists():
            with open(path, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
                col = "Ticker" if rows and "Ticker" in rows[0] else (list(rows[0].keys())[0] if rows else None)
                if col:
                    return [r[col].strip().upper() for r in rows if r.get(col)]
    return provider.universe_tickers()


def _existing_meta() -> dict[str, dict[str, str]]:
    if not MASTER_CSV.exists():
        return {}
    with open(MASTER_CSV, newline="", encoding="utf-8") as fh:
        return {r["Ticker"].upper(): r for r in csv.DictReader(fh) if r.get("Ticker")}


def build(limit: Optional[int] = None) -> dict[str, Any]:
    """Bangun ulang master_data_syariah.csv. Kembalikan ringkasan."""
    tickers = _ticker_list()
    meta = _existing_meta()
    n_fetch = limit if limit else len(tickers)  # limit: refresh sebagian, sisanya dipertahankan

    rows: list[dict[str, str]] = []
    ok = fail = kept = 0
    for idx, tk in enumerate(tickers):
        prev = meta.get(tk, {})
        if idx >= n_fetch and prev:          # di luar limit → pertahankan baris lama
            rows.append({c: prev.get(c, "N/A") for c in COLUMNS})
            kept += 1
            continue
        rec = {c: "N/A" for c in COLUMNS}
        rec["Ticker"] = tk
        rec["Nama Perusahaan"] = prev.get("Nama Perusahaan", "")
        rec["Sektor"] = prev.get("Sektor", "")
        try:
            info = provider.get_info(tk)
            if not info:
                rec["Source"] = "stale" if prev else "N/A"
                if prev:
                    rec = {**rec, **{k: prev.get(k, rec[k]) for k in COLUMNS if k != "Source"}}
                rows.append(rec)
                fail += 1
                continue
            rec["Nama Perusahaan"] = info.get("longName") or info.get("shortName") or rec["Nama Perusahaan"]
            rec["Sektor"] = info.get("sector") or rec["Sektor"]
            rec["EPS QnQ"] = _pct(info.get("earningsQuarterlyGrowth"))
            rec["ROA"] = _pct(info.get("returnOnAssets"))
            rec["ROE"] = _pct(info.get("returnOnEquity"))
            rec["NPM"] = _pct(info.get("profitMargins"))
            rec["PER"] = _x(info.get("trailingPE"))
            rec["PBV"] = _x(info.get("priceToBook"), max_realistic=100)
            rec["DER"] = _pct_smart(info.get("debtToEquity"))
            rec["PEG"] = _x(info.get("trailingPegRatio") or info.get("pegRatio"))
            rec["BVPS"] = _num(info.get("bookValue"))
            rec["MP"] = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
            fs, so = info.get("floatShares"), info.get("sharesOutstanding")
            rec["Free Float"] = f"{fs / so * 100:.2f}%" if (fs and so) else prev.get("Free Float", "N/A")
            rec["Dividend Yield"] = _pct_smart(info.get("dividendYield"))
            rec["Source"] = "yfinance"
            ok += 1
        except Exception:
            rec["Source"] = "error"
            fail += 1
        rows.append(rec)
        time.sleep(0.15)  # jeda ringan agar tidak rate-limited

    # tulis CSV
    with open(MASTER_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    summary = {"total": len(rows), "ok": ok, "fail": fail, "kept": kept, "path": str(MASTER_CSV)}
    try:
        STATUS.write_text(json.dumps({**summary, "ts": time.time()}))
    except Exception:
        pass
    # invalidasi cache master_data
    try:
        from app.data import master_data
        master_data._rows.cache_clear()  # type: ignore[attr-defined]
        master_data._by_ticker.cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    return summary


def status() -> dict[str, Any]:
    if STATUS.exists():
        try:
            d = json.loads(STATUS.read_text())
            d["last_build_iso"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(d.get("ts", 0)))
            return d
        except Exception:
            pass
    return {"total": None, "last_build_iso": "belum pernah", "path": str(MASTER_CSV)}
