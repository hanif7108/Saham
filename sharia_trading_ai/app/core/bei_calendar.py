"""
Kalender Hari Libur Bursa Efek Indonesia (BEI/IDX).

Sumber data: app/data/bei_holidays.json (kalender resmi BEI, dapat ditambah
pengguna). Dipakai mendeteksi bursa tutup secara presisi (libur nasional/cuti
bersama/libur akhir tahun) — bukan sekadar akhir pekan atau data basi.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from app.config import DATA_DIR

CAL = DATA_DIR / "bei_holidays.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(CAL.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"source": "", "holidays": {}}


def _save(data: dict[str, Any]) -> None:
    CAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def holidays() -> dict[str, str]:
    return _load().get("holidays", {})


def source() -> str:
    return _load().get("source", "")


def is_holiday(d: date) -> Optional[str]:
    """Nama libur bila tanggal `d` adalah hari libur bursa; selain itu None."""
    return holidays().get(d.isoformat())


def next_holiday(frm: Optional[date] = None) -> Optional[dict[str, Any]]:
    frm = frm or date.today()
    fut = sorted((k, v) for k, v in holidays().items() if k >= frm.isoformat())
    if not fut:
        return None
    k, v = fut[0]
    return {"date": k, "name": v, "in_days": (date.fromisoformat(k) - frm).days}


def upcoming(frm: Optional[date] = None, limit: int = 12) -> list[dict[str, str]]:
    f = (frm or date.today()).isoformat()
    fut = sorted((k, v) for k, v in holidays().items() if k >= f)
    return [{"date": k, "name": v} for k, v in fut[:limit]]


def add_holiday(d: str, name: str) -> dict[str, str]:
    """Tambah/ubah satu hari libur (format tanggal YYYY-MM-DD)."""
    date.fromisoformat(d)                     # validasi format
    data = _load()
    data.setdefault("holidays", {})[d] = name
    _save(data)
    return {"date": d, "name": name}


def remove_holiday(d: str) -> bool:
    data = _load()
    if d in data.get("holidays", {}):
        del data["holidays"][d]
        _save(data)
        return True
    return False
