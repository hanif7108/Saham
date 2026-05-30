"""
Build Master Data Saham Syariah US
===================================
Mengunduh data fundamental untuk seluruh ticker di daftar_saham_syariah_us.csv,
simpan ke master_data_syariah_us.csv. Mirror dari build_master_data.py tapi
tanpa suffix .JK dan tanpa scraper IDX.

Data yang diambil:
  - 6 Magic Numbers: EPS QnQ, ROA, ROE, NPM, DER, PER, PBV
  - Free Float, Dividend Yield, PEG
  - Sektor, Nama Perusahaan
  - AAOIFI compliance flag (dari modules.aaoifi)
"""

import os
import sys
import time

import pandas as pd
import yfinance as yf

SAHAM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SAHAM_DIR)

from modules.aaoifi import evaluate_from_yfinance_info


def _fmt_pct(v, factor=100):
    if v is None:
        return "N/A"
    try:
        return f"{float(v) * factor:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct_smart(v, expected_max=30):
    if v is None:
        return "N/A"
    try:
        x = float(v)
        if x < 1.5:
            x = x * 100
        elif x > expected_max:
            x = x / 100
        return f"{x:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_x(v, max_realistic=1000):
    if v is None:
        return "N/A"
    try:
        x = float(v)
        if abs(x) > max_realistic or x < -max_realistic:
            return "N/A"
        return f"{x:.2f}x"
    except (TypeError, ValueError):
        return "N/A"


def build_master_us_csv(input_csv: str, output_csv: str):
    print("=" * 60)
    print("BUILD MASTER DATA SAHAM SYARIAH US (yfinance + AAOIFI)")
    print("=" * 60)

    if not os.path.exists(input_csv):
        print(f"File sumber {input_csv} tidak ditemukan!")
        return

    df_input = pd.read_csv(input_csv)
    master_records = []

    from modules.cache import Cache
    cache = Cache(os.path.join(SAHAM_DIR, "cache"))

    for index, row in df_input.iterrows():
        ticker = str(row["Ticker"]).strip().upper()
        nama_csv = str(row.get("Name", "") or "").strip()
        sektor_csv = str(row.get("Sector", "") or "").strip()

        print(f"[{index + 1}/{len(df_input)}] {ticker}...")

        record = {
            "Ticker": ticker,
            "Nama Perusahaan": nama_csv,
            "Sektor": sektor_csv or "N/A",
            "Industry": "N/A",
            "MarketCap": "N/A",
            "EPS QnQ": "N/A",
            "ROA": "N/A",
            "ROE": "N/A",
            "NPM": "N/A",
            "PER": "N/A",
            "PBV": "N/A",
            "DER": "N/A",
            "PEG": "N/A",
            "BVPS": "N/A",
            "MP": "N/A",
            "Free Float": "N/A",
            "Dividend Yield": "N/A",
            "AAOIFI Status": "UNKNOWN",
            "AAOIFI Reason": "",
            "Source": ""
        }

        try:
            stock = yf.Ticker(ticker)  # US: tanpa .JK
            info = stock.info or {}

            if not nama_csv:
                record["Nama Perusahaan"] = (info.get("longName") or info.get("shortName") or "")[:80]
            record["Sektor"] = info.get("sector", sektor_csv) or sektor_csv or "N/A"
            record["Industry"] = info.get("industry", "N/A") or "N/A"

            mcap = info.get("marketCap")
            if mcap:
                # Format jadi B/T USD
                if mcap >= 1e12:
                    record["MarketCap"] = f"${mcap/1e12:.2f}T"
                elif mcap >= 1e9:
                    record["MarketCap"] = f"${mcap/1e9:.2f}B"
                else:
                    record["MarketCap"] = f"${mcap/1e6:.0f}M"

            record["EPS QnQ"] = _fmt_pct(info.get("earningsQuarterlyGrowth"))
            record["ROA"] = _fmt_pct(info.get("returnOnAssets"))
            record["ROE"] = _fmt_pct(info.get("returnOnEquity"))
            record["NPM"] = _fmt_pct(info.get("profitMargins"))

            bvps = info.get("bookValue")
            if bvps is not None:
                record["BVPS"] = f"{float(bvps):.2f}"

            mp = info.get("currentPrice") or info.get("regularMarketPrice")
            if mp is not None:
                record["MP"] = f"{float(mp):.2f}"

            record["PER"] = _fmt_x(info.get("trailingPE"))
            record["PBV"] = _fmt_x(info.get("priceToBook"))
            record["DER"] = _fmt_pct_smart(info.get("debtToEquity"), expected_max=500)
            record["PEG"] = _fmt_x(info.get("pegRatio"))
            record["Dividend Yield"] = _fmt_pct_smart(info.get("dividendYield"), expected_max=30)

            float_shares = info.get("floatShares")
            shares_out = info.get("sharesOutstanding")
            if float_shares and shares_out:
                record["Free Float"] = f"{(float_shares / shares_out) * 100:.2f}%"

            # AAOIFI screening
            aaoifi_res = evaluate_from_yfinance_info(ticker, info)
            record["AAOIFI Status"] = aaoifi_res["summary"]  # PASS / FAIL / NEEDS_AUDIT
            # Concat key failed reasons
            reasons = []
            for key, chk in aaoifi_res["checks"].items():
                if chk["pass"] is False:
                    reasons.append(f"{key}:FAIL({chk.get('value')})")
                elif chk["pass"] is None and key != "non_permissible_income":
                    reasons.append(f"{key}:?")
            record["AAOIFI Reason"] = "; ".join(reasons) if reasons else "all checks OK (manual audit non-permissible income disarankan)"

            # Pre-warm history cache
            try:
                for p in ("3mo", "6mo", "1y"):
                    cache.get_history(ticker, period=p, force_refresh=True, market="US")
            except Exception as ce:
                print(f"  [!] Gagal pre-warm cache {ticker}: {ce}")

            record["Source"] = "yfinance"
        except Exception as e:
            print(f"  [!] yfinance gagal: {e}")

        master_records.append(record)
        time.sleep(1.5)  # rate limit

    # Pre-warm indeks US (^GSPC S&P 500, ^IXIC NASDAQ Composite, ^NDX Nasdaq 100)
    for idx_sym in ("^GSPC", "^IXIC", "^NDX"):
        try:
            print(f"Pre-warming {idx_sym} history cache...")
            cache.get_history(idx_sym, period="1y", force_refresh=True)
        except Exception as ce:
            print(f"Gagal pre-warm {idx_sym}: {ce}")

    df_master = pd.DataFrame(master_records)
    df_master.to_csv(output_csv, index=False)
    print()
    print("=" * 60)
    print(f"Sukses! {len(df_master)} ticker US disimpan di: {output_csv}")

    # Summary by AAOIFI status
    summary = df_master["AAOIFI Status"].value_counts().to_dict()
    print(f"AAOIFI summary: {summary}")
    print("=" * 60)


if __name__ == "__main__":
    input_file = os.path.join(SAHAM_DIR, "daftar_saham_syariah_us.csv")
    output_file = os.path.join(SAHAM_DIR, "master_data_syariah_us.csv")
    build_master_us_csv(input_file, output_file)
