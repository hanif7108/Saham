"""
Portfolio Snapshot — Time-series nilai aset harian
==================================================
Merekam snapshot nilai total aset (net worth) + breakdown kelas aset per hari,
untuk grafik pertumbuhan dan persentase pertumbuhan periodik (harian/mingguan/bulanan).

Penyimpanan: CSV sederhana (1 baris per tanggal). Idempotent per hari —
pemanggilan berulang di hari yang sama akan meng-update baris hari itu
(bukan menambah duplikat).

Kolom:
  date, net_worth_rp, saham_idx_rp, saham_us_rp, emas_rp, kas_rp,
  invested_rp, pnl_rp
"""

from __future__ import annotations

import os
from datetime import datetime, date
from typing import Dict, List, Any

import pandas as pd

COLUMNS = [
    "date", "net_worth_rp", "saham_idx_rp", "saham_us_rp",
    "emas_rp", "kas_rp", "invested_rp", "pnl_rp",
]


def record_snapshot(path: str, snapshot: Dict[str, Any], when: date | None = None) -> None:
    """Upsert snapshot untuk tanggal `when` (default: hari ini).

    snapshot dict diharapkan punya key:
      net_worth_rp, saham_idx_rp, saham_us_rp, emas_rp, kas_rp, invested_rp, pnl_rp
    """
    day = (when or date.today()).isoformat()
    row = {
        "date": day,
        "net_worth_rp": round(float(snapshot.get("net_worth_rp") or 0), 0),
        "saham_idx_rp": round(float(snapshot.get("saham_idx_rp") or 0), 0),
        "saham_us_rp": round(float(snapshot.get("saham_us_rp") or 0), 0),
        "emas_rp": round(float(snapshot.get("emas_rp") or 0), 0),
        "kas_rp": round(float(snapshot.get("kas_rp") or 0), 0),
        "invested_rp": round(float(snapshot.get("invested_rp") or 0), 0),
        "pnl_rp": round(float(snapshot.get("pnl_rp") or 0), 0),
    }

    try:
        if os.path.exists(path):
            df = pd.read_csv(path)
            # pastikan semua kolom ada
            for c in COLUMNS:
                if c not in df.columns:
                    df[c] = 0
            df = df[df["date"] != day]  # buang baris hari ini kalau ada → upsert
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row], columns=COLUMNS)
        df = df.sort_values("date").reset_index(drop=True)
        tmp = path + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
    except Exception:
        # snapshot bersifat best-effort; jangan ganggu request utama
        pass


def load_snapshots(path: str) -> List[Dict[str, Any]]:
    """Baca semua snapshot terurut tanggal naik."""
    if not os.path.exists(path):
        return []
    try:
        df = pd.read_csv(path)
        if df.empty:
            return []
        df = df.sort_values("date").reset_index(drop=True)
        return df.to_dict(orient="records")
    except Exception:
        return []


def _pct_change(series: List[float]) -> float:
    if len(series) < 2 or series[0] == 0:
        return 0.0
    return round((series[-1] - series[0]) / series[0] * 100, 2)


def compute_growth(snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Hitung % pertumbuhan net worth untuk beberapa horizon waktu.

    Mengembalikan dict: { daily, weekly, monthly, all, latest, since_date }.
    Pendekatan: ambil net_worth terakhir vs net_worth N hari ke belakang
    (snapshot terdekat <= target date).
    """
    if not snapshots:
        return {"daily": 0.0, "weekly": 0.0, "monthly": 0.0, "all": 0.0,
                "latest": 0.0, "since_date": None}

    # Parse tanggal
    parsed = []
    for s in snapshots:
        try:
            d = datetime.fromisoformat(str(s["date"])).date()
        except Exception:
            continue
        parsed.append((d, float(s.get("net_worth_rp") or 0)))
    if not parsed:
        return {"daily": 0.0, "weekly": 0.0, "monthly": 0.0, "all": 0.0,
                "latest": 0.0, "since_date": None}

    parsed.sort(key=lambda x: x[0])
    latest_date, latest_val = parsed[-1]

    def value_n_days_ago(n: int) -> float:
        target = latest_date.toordinal() - n
        # cari snapshot dengan tanggal <= target, ambil yang terbaru
        candidate = None
        for d, v in parsed:
            if d.toordinal() <= target:
                candidate = v
            else:
                break
        # kalau tidak ada yang cukup tua, pakai snapshot pertama
        return candidate if candidate is not None else parsed[0][1]

    def growth_for(n: int) -> float:
        old = value_n_days_ago(n)
        if old <= 0:
            return 0.0
        return round((latest_val - old) / old * 100, 2)

    first_val = parsed[0][1]
    all_growth = round((latest_val - first_val) / first_val * 100, 2) if first_val > 0 else 0.0

    return {
        "daily": growth_for(1),
        "weekly": growth_for(7),
        "monthly": growth_for(30),
        "all": all_growth,
        "latest": round(latest_val, 0),
        "since_date": parsed[0][0].isoformat(),
        "n_points": len(parsed),
    }
