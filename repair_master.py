"""
Repair Master Data
==================
Memperbaiki nilai outlier di master_data_syariah.csv tanpa perlu refetch yfinance.
- Dividend Yield > 30% kemungkinan double-multiply → /100
- DER > 500% kemungkinan double-multiply → /100

Jalankan: python3 repair_master.py
"""

import os
import sys

import pandas as pd

SAHAM_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_FILE = os.path.join(SAHAM_DIR, "master_data_syariah.csv")


def _parse_pct(s):
    if pd.isna(s):
        return None
    s = str(s).strip()
    if s in ("N/A", "ERROR", ""):
        return None
    s = s.replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_x(s):
    if pd.isna(s):
        return None
    s = str(s).strip()
    if s in ("N/A", "ERROR", ""):
        return None
    s = s.replace("x", "").replace("X", "")
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(x):
    if x is None:
        return "N/A"
    return f"{x:.2f}%"


def _fmt_x(x):
    if x is None:
        return "N/A"
    return f"{x:.2f}x"


def repair():
    if not os.path.exists(MASTER_FILE):
        print(f"File {MASTER_FILE} tidak ditemukan!")
        sys.exit(1)

    df = pd.read_csv(MASTER_FILE, keep_default_na=False)
    n = len(df)
    fixed_div = 0
    fixed_der = 0
    flagged_pbv = 0
    flagged_per = 0
    flagged_peg = 0

    for i, row in df.iterrows():
        # Dividend Yield: realistic 0-30%
        dy = _parse_pct(row.get("Dividend Yield"))
        if dy is not None and dy > 30:
            new_val = dy / 100
            df.at[i, "Dividend Yield"] = _fmt(new_val)
            fixed_div += 1

        # DER: realistic biasanya < 500%
        der = _parse_pct(row.get("DER"))
        if der is not None and der > 500:
            new_val = der / 100
            df.at[i, "DER"] = _fmt(new_val)
            fixed_der += 1

        # PBV: realistic 0-50x (saham normal). Outlier dari yfinance bug → N/A
        pbv = _parse_x(row.get("PBV"))
        if pbv is not None and (pbv > 1000 or pbv < -1000):
            df.at[i, "PBV"] = "N/A"
            flagged_pbv += 1

        # PER: realistic -200x to 500x (loss → negative PER). Outlier → N/A
        per = _parse_x(row.get("PER"))
        if per is not None and (per > 1000 or per < -1000):
            df.at[i, "PER"] = "N/A"
            flagged_per += 1

        # PEG: realistic -10 to 10
        if "PEG" in df.columns:
            peg = _parse_x(row.get("PEG"))
            if peg is not None and (peg > 50 or peg < -50):
                df.at[i, "PEG"] = "N/A"
                flagged_peg += 1

    df.to_csv(MASTER_FILE, index=False)
    print(f"Repair selesai: {n} ticker")
    print(f"  Dividend Yield diperbaiki: {fixed_div}")
    print(f"  DER diperbaiki:           {fixed_der}")
    print(f"  PBV outlier → N/A:        {flagged_pbv}")
    print(f"  PER outlier → N/A:        {flagged_per}")
    print(f"  PEG outlier → N/A:        {flagged_peg}")


if __name__ == "__main__":
    repair()
