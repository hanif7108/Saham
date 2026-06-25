"""
IDX / Stockbit Fundamental Scraper
==================================
Mengambil data fundamental saham IDX dari sumber terbuka:
1. Stockbit (HTML public)
2. RTI Business / IDX (fallback)
3. yfinance (fallback terakhir, sudah ada di build_master_data.py)

Pendekatan defensif: scraper bisa gagal kapan saja karena perubahan HTML.
Karena itu setiap fungsi mengembalikan dict dengan field 'source' dan 'ok'
agar pipeline yang memanggilnya bisa fallback ke yfinance jika perlu.

Catatan: scraping HARUS rate-limited (delay antar request) untuk menghormati
servernya. Default 1.5 detik antar request.

Contoh penggunaan:
    from modules.idx_scraper import fetch_stockbit_fundamentals
    data = fetch_stockbit_fundamentals("BRIS")
    print(data)
"""

import re
import time
from typing import Optional

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 10  # detik


# ----------------------------- HELPERS ----------------------------- #

def _to_float(text: Optional[str]) -> Optional[float]:
    """Konversi string seperti '17.50%', '1.234,56', '12.3x' ke float."""
    if text is None:
        return None
    s = str(text).strip()
    if s == "" or s.lower() in {"n/a", "-", "null", "nan"}:
        return None
    # Hapus simbol persen, kali, mata uang
    s = s.replace("%", "").replace("x", "").replace("X", "")
    s = s.replace("Rp", "").replace("IDR", "").strip()
    # Format Indonesia: ribuan = '.', desimal = ','. Detect dan ubah.
    if "," in s and "." in s:
        # asumsikan format "1.234,56"
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _safe_get(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[str]:
    """HTTP GET dengan UA & timeout. Return text atau None bila gagal."""
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
        return None
    except requests.RequestException:
        return None


# ----------------------------- STOCKBIT ----------------------------- #

# Stockbit page URL: https://stockbit.com/symbol/<TICKER>
# Halaman publik berisi widget fundamental ringkas (PER, PBV, ROE, dll).
# Mereka pakai JS-render — tetapi sebagian metric tersedia di JSON-LD / meta.

def fetch_stockbit_fundamentals(ticker: str) -> dict:
    """
    Coba ambil data fundamental dari Stockbit.
    Return dict dengan key: per, pbv, roe, eps_growth, der, dividend_yield, source, ok.
    """
    url = f"https://stockbit.com/symbol/{ticker.upper()}"
    html = _safe_get(url)
    result = {
        "ticker": ticker.upper(),
        "source": "stockbit",
        "ok": False,
        "per": None, "pbv": None, "roe": None,
        "eps_growth": None, "der": None, "dividend_yield": None,
    }
    if not html:
        return result

    # Parse pakai regex sederhana karena halaman heavy JS.
    # Kita cari pola key di window.__INITIAL_STATE__ atau meta og:description
    patterns = {
        "per": [r'"PER"\s*:\s*"?([\-0-9.,]+)"?', r'PER[^0-9\-]+([\-0-9.,]+)\s*x'],
        "pbv": [r'"PBV"\s*:\s*"?([\-0-9.,]+)"?', r'PBV[^0-9\-]+([\-0-9.,]+)\s*x'],
        "roe": [r'"ROE"\s*:\s*"?([\-0-9.,]+)"?', r'ROE[^0-9\-]+([\-0-9.,]+)\s*%'],
        "der": [r'"DER"\s*:\s*"?([\-0-9.,]+)"?', r'DER[^0-9\-]+([\-0-9.,]+)\s*%'],
        "eps_growth": [r'"earningsQuarterlyGrowth"\s*:\s*"?([\-0-9.,]+)"?'],
        "dividend_yield": [r'"dividendYield"\s*:\s*"?([\-0-9.,]+)"?'],
    }

    found_any = False
    for key, pats in patterns.items():
        for p in pats:
            m = re.search(p, html, flags=re.IGNORECASE)
            if m:
                val = _to_float(m.group(1))
                if val is not None:
                    result[key] = val
                    found_any = True
                    break

    result["ok"] = found_any
    return result


# ----------------------------- RTI ----------------------------- #

# RTI Business: https://www.rti.co.id/Stock/StockSummary?code=<TICKER>
# Halaman ini lebih server-side rendered, jadi data fundamental ada di tabel HTML.

def fetch_rti_fundamentals(ticker: str) -> dict:
    """Ambil ringkasan fundamental dari RTI."""
    url = f"https://www.rti.co.id/Stock/StockSummary?code={ticker.upper()}"
    html = _safe_get(url)
    result = {
        "ticker": ticker.upper(),
        "source": "rti",
        "ok": False,
        "per": None, "pbv": None, "roe": None,
        "eps_growth": None, "der": None, "dividend_yield": None,
    }
    if not html:
        return result

    # RTI biasanya menampilkan: PER xxx, PBV xxx, ROE xxx, dst di tabel.
    # Pakai regex pola label diikuti angka.
    label_patterns = {
        "per": r'PER[^<]*<[^>]+>\s*([\-0-9.,]+)',
        "pbv": r'PBV[^<]*<[^>]+>\s*([\-0-9.,]+)',
        "roe": r'ROE[^<]*<[^>]+>\s*([\-0-9.,]+)',
        "der": r'DER[^<]*<[^>]+>\s*([\-0-9.,]+)',
    }
    found_any = False
    for key, p in label_patterns.items():
        m = re.search(p, html, flags=re.IGNORECASE)
        if m:
            val = _to_float(m.group(1))
            if val is not None:
                result[key] = val
                found_any = True

    result["ok"] = found_any
    return result


# ----------------------------- ORCHESTRATION ----------------------------- #

def fetch_fundamentals(ticker: str, delay: float = 1.5) -> dict:
    """
    Coba semua sumber secara berurutan, gabungkan hasil.
    Field None dari source pertama akan diisi dari source berikutnya.
    """
    merged = {
        "ticker": ticker.upper(),
        "per": None, "pbv": None, "roe": None,
        "eps_growth": None, "der": None, "dividend_yield": None,
        "sources_used": []
    }

    for fetcher in (fetch_stockbit_fundamentals, fetch_rti_fundamentals):
        data = fetcher(ticker)
        if data.get("ok"):
            merged["sources_used"].append(data["source"])
            for k in ("per", "pbv", "roe", "eps_growth", "der", "dividend_yield"):
                if merged[k] is None and data.get(k) is not None:
                    merged[k] = data[k]
        time.sleep(delay)

    # Cek apakah ada data
    has_data = any(merged[k] is not None for k in
                   ("per", "pbv", "roe", "eps_growth", "der", "dividend_yield"))
    merged["ok"] = has_data
    return merged


if __name__ == "__main__":
    # Smoke test
    for tk in ["BRIS", "TLKM"]:
        print(f"\n=== {tk} ===")
        data = fetch_fundamentals(tk, delay=1.0)
        for k, v in data.items():
            print(f"  {k}: {v}")
