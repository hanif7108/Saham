"""
Build Master Data Saham Syariah
================================
Mengunduh data fundamental untuk seluruh ticker di daftar_saham_syariah.csv,
gabungkan yfinance + scraper IDX (kalau tersedia), simpan ke master_data_syariah.csv.

Data yang diambil:
  - 6 Magic Numbers: EPS QnQ, ROE, NPM, DER, PER, PBV
  - Free Float, Dividend Yield, PEG
  - Sektor, Nama Perusahaan
"""

import os
import sys
import time

import pandas as pd
import yfinance as yf

# Tambahkan parent ke path supaya bisa import modules
SAHAM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SAHAM_DIR)

from modules.google_finance import fetch_google_price

try:
    from modules.idx_scraper import fetch_fundamentals as scraper_fetch
    SCRAPER_AVAILABLE = True
except ImportError:
    SCRAPER_AVAILABLE = False


def _fmt_pct(v, factor=100):
    """Format float as percent string."""
    if v is None:
        return "N/A"
    try:
        return f"{float(v) * factor:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct_smart(v, expected_max=30):
    """
    Format dividend yield / metric yang field-nya inkonsisten di yfinance.
    Kadang yfinance return decimal (0.092 = 9.2%), kadang sudah persen (9.2 = 9.2%).
    Auto-detect dengan expected_max threshold:
      - jika v < 1.5 → asumsikan decimal, kalikan 100
      - jika v > expected_max → diasumsikan ada double-multiply / data salah, /100
      - sisanya: pakai apa adanya (sudah dalam persen)
    """
    if v is None:
        return "N/A"
    try:
        x = float(v)
        if x < 1.5:
            x = x * 100
        elif x > expected_max:
            x = x / 100
        # else: pakai apa adanya
        return f"{x:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_x(v, max_realistic=1000):
    """Format ratio (PER/PBV/PEG). Buang outlier > max_realistic (yfinance kadang bug)."""
    if v is None:
        return "N/A"
    try:
        x = float(v)
        if abs(x) > max_realistic or x < -max_realistic:
            return "N/A"  # outlier
        return f"{x:.2f}x"
    except (TypeError, ValueError):
        return "N/A"


def build_master_csv(input_csv: str, output_csv: str, use_scraper: bool = True):
    print("=" * 60)
    print("BUILD MASTER DATA SAHAM SYARIAH (yfinance + scraper)")
    print("=" * 60)

    if not os.path.exists(input_csv):
        print(f"File sumber {input_csv} tidak ditemukan!")
        return

    df_input = pd.read_csv(input_csv)
    master_records = []

    from modules.cache import Cache
    cache = Cache(os.path.join(SAHAM_DIR, "cache"))

    use_scraper = use_scraper and SCRAPER_AVAILABLE

    for index, row in df_input.iterrows():
        ticker = row["Ticker"]
        nama = row.get("Nama Perusahaan", "")
        yf_ticker = f"{ticker}.JK"

        print(f"[{index + 1}/{len(df_input)}] {ticker}...")

        record = {
            "Ticker": ticker,
            "Nama Perusahaan": nama,
            "Sektor": "N/A",
            "EPS QnQ": "N/A",
            "ROA": "N/A",          # NEW (Paket B)
            "ROE": "N/A",
            "NPM": "N/A",
            "PER": "N/A",
            "PBV": "N/A",
            "DER": "N/A",
            "PEG": "N/A",
            "BVPS": "N/A",         # NEW (Paket B)
            "MP": "N/A",           # NEW (current market price)
            "Free Float": "N/A",
            "Dividend Yield": "N/A",
            "Source": ""
        }

        # ---- Google Finance ----
        try:
            gf_res = fetch_google_price(ticker)
            if gf_res.get("ok") and gf_res.get("price") is not None:
                record["MP"] = f"{gf_res['price']:.2f}"
                record["Source"] = "google"
            else:
                if gf_res.get("error"):
                    print(f"  [!] Google Finance error for {ticker}: {gf_res['error']}")
        except Exception as e:
            print(f"  [!] Google Finance gagal: {e}")

        # ---- yfinance ----
        try:
            stock = yf.Ticker(yf_ticker)
            info = stock.info or {}

            # Nama perusahaan: pakai dari CSV input dulu, fallback ke yfinance
            if not nama or pd.isna(nama):
                record["Nama Perusahaan"] = (info.get("longName") or info.get("shortName") or "")[:80]

            record["Sektor"] = info.get("sector", "N/A") or "N/A"
            record["EPS QnQ"] = _fmt_pct(info.get("earningsQuarterlyGrowth"))
            record["ROA"] = _fmt_pct(info.get("returnOnAssets"))
            record["ROE"] = _fmt_pct(info.get("returnOnEquity"))
            record["NPM"] = _fmt_pct(info.get("profitMargins"))

            # BVPS (Book Value per Share) & MP (Market Price)
            bvps = info.get("bookValue")
            mp = info.get("currentPrice") or info.get("regularMarketPrice")
            if bvps is not None:
                record["BVPS"] = f"{float(bvps):.2f}"
            
            # Gunakan yfinance jika Google Finance tidak mengembalikan harga
            if record["MP"] == "N/A" and mp is not None:
                record["MP"] = f"{float(mp):.2f}"

            record["PER"] = _fmt_x(info.get("trailingPE"))
            record["PBV"] = _fmt_x(info.get("priceToBook"))
            # DER yfinance: kadang ratio (0.5), kadang sudah persen (50). Auto.
            record["DER"] = _fmt_pct_smart(info.get("debtToEquity"), expected_max=500)
            record["PEG"] = _fmt_x(info.get("pegRatio"))
            # Dividend yield: yfinance umumnya sudah % (mis 9.2 = 9.2%). Auto.
            record["Dividend Yield"] = _fmt_pct_smart(info.get("dividendYield"), expected_max=30)

            float_shares = info.get("floatShares")
            shares_out = info.get("sharesOutstanding")
            if float_shares and shares_out:
                record["Free Float"] = f"{(float_shares / shares_out) * 100:.2f}%"

            # Pre-warm history cache (3mo, 6mo, 1y) untuk kebutuhan analisis teknikal offline harian
            try:
                for p in ("3mo", "6mo", "1y"):
                    cache.get_history(ticker, period=p, force_refresh=True)
            except Exception as ce:
                print(f"  [!] Gagal pre-warm history cache {ticker}: {ce}")

            if record["Source"] == "google":
                record["Source"] = "google+yfinance"
            else:
                record["Source"] = "yfinance"
        except Exception as e:
            print(f"  [!] yfinance gagal: {e}")

        # ---- Scraper fallback (untuk field yang masih N/A) ----
        if use_scraper:
            missing = [k for k in ("PER", "PBV", "ROE", "DER")
                       if record[k] == "N/A"]
            if missing:
                try:
                    scraped = scraper_fetch(ticker, delay=1.0)
                    if scraped.get("ok"):
                        if record["PER"] == "N/A" and scraped.get("per"):
                            record["PER"] = _fmt_x(scraped["per"])
                        if record["PBV"] == "N/A" and scraped.get("pbv"):
                            record["PBV"] = _fmt_x(scraped["pbv"])
                        if record["ROE"] == "N/A" and scraped.get("roe"):
                            record["ROE"] = f"{scraped['roe']:.2f}%"
                        if record["DER"] == "N/A" and scraped.get("der"):
                            record["DER"] = f"{scraped['der']:.2f}%"
                        record["Source"] += "+" + "+".join(scraped.get("sources_used", []))
                except Exception as e:
                    print(f"  [!] scraper error: {e}")

        master_records.append(record)
        time.sleep(1.5)  # rate limit

    # Pre-warm IHSG (^JKSE) history cache
    try:
        print("Pre-warming IHSG (^JKSE) history cache...")
        cache.get_history("^JKSE", period="6mo", force_refresh=True)
    except Exception as ce:
        print(f"Gagal pre-warm IHSG cache: {ce}")

    df_master = pd.DataFrame(master_records)
    df_master.to_csv(output_csv, index=False)
    print()
    print("=" * 60)
    print(f"Sukses! {len(df_master)} ticker disimpan di: {output_csv}")
    print("=" * 60)


if __name__ == "__main__":
    input_file = os.path.join(SAHAM_DIR, "daftar_saham_syariah.csv")
    output_file = os.path.join(SAHAM_DIR, "master_data_syariah.csv")
    build_master_csv(input_file, output_file)
