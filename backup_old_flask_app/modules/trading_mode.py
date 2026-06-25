"""
Trading Mode Configuration
==========================
Konfigurasi threshold cut-loss / take-profit per mode trading.
Di-control via env var TRADING_MODE.

Modes:
  - swing    : Taichi default (CL -3% / TP +6%)        — 1-7 hari hold
  - scalping : aggressive       (CL -1% / TP +2%)       — intraday, beberapa jam
  - position : jangka panjang   (CL -7% / TP +20%)      — minggu/bulan (O'Neil)
"""

import os

MODES = {
    "swing": {
        "name": "Swing Trading (Taichi)",
        "cut_loss_pct": -3.0,
        "take_profit_pct": 6.0,
        "scan_interval_min": 30,
        "description": "1-7 hari hold, sesuai panduan Doddy Eka Putra"
    },
    "scalping": {
        "name": "Scalping",
        "cut_loss_pct": -1.0,
        "take_profit_pct": 2.0,
        "scan_interval_min": 5,
        "description": "Intraday cepat, masuk-keluar dalam jam yang sama"
    },
    "position": {
        "name": "Position Trading (O'Neil)",
        "cut_loss_pct": -7.0,
        "take_profit_pct": 20.0,
        "scan_interval_min": 60,
        "description": "Hold mingguan/bulanan, original O'Neil rule"
    },
}


def get_mode() -> str:
    return os.environ.get("TRADING_MODE", "swing").lower()


def get_config() -> dict:
    mode = get_mode()
    return MODES.get(mode, MODES["swing"])


def get_cut_loss_pct() -> float:
    return get_config()["cut_loss_pct"]


def get_take_profit_pct() -> float:
    return get_config()["take_profit_pct"]


def get_scan_interval_min() -> int:
    return get_config()["scan_interval_min"]
