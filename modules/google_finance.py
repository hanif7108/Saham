"""
Google Finance Price Scraper
============================
Mengambil harga saham terkini (real-time/delay minimal) dari Google Finance:
URL: https://www.google.com/finance/quote/<TICKER>:IDX

Metode: Menggunakan ekspresi reguler (regex) untuk mengekstrak data dari
blok script `AF_initDataCallback` yang dikirim oleh Google.
"""

import re
import time
import requests
from typing import Optional

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_TIMEOUT = 10  # detik


def fetch_google_price(ticker: str, timeout: int = REQUEST_TIMEOUT) -> dict:
    """
    Mengambil data harga terkini untuk ticker bursa IDX dari Google Finance.
    
    Return dict:
        {
            "ok": bool,
            "ticker": str,
            "price": float atau None,
            "change": float atau None,
            "pct_change": float atau None,
            "source": "google_finance",
            "error": str atau None
        }
    """
    ticker_clean = ticker.upper().strip()
    url = f"https://www.google.com/finance/quote/{ticker_clean}:IDX"
    
    result = {
        "ok": False,
        "ticker": ticker_clean,
        "price": None,
        "change": None,
        "pct_change": None,
        "source": "google_finance",
        "error": None
    }
    
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        if r.status_code != 200:
            result["error"] = f"HTTP status {r.status_code}"
            return result
        
        html = r.text
        
        # Regex refined to target: [ "TICKER", "IDX" ], company_name, 0, "IDR", [ price, change, pct_change ]
        pattern = (
            r'\[\s*"' + re.escape(ticker_clean) + 
            r'"\s*,\s*"IDX"\s*\]\s*,\s*(?:"[^"]*"|[^,]*)\s*,\s*0\s*,\s*"IDR"\s*,\s*\[\s*([0-9.-]+)\s*,\s*([0-9.-]+)\s*,\s*([0-9.-]+)'
        )
        
        match = re.search(pattern, html)
        if match:
            try:
                result["price"] = float(match.group(1))
                result["change"] = float(match.group(2))
                result["pct_change"] = float(match.group(3))
                result["ok"] = True
            except (ValueError, TypeError) as ve:
                result["error"] = f"Value conversion error: {ve}"
        else:
            # Fallback regex jika nama perusahaan atau flag berbeda, coba cari harga saja
            fallback_pattern = (
                r'\[\s*"' + re.escape(ticker_clean) + 
                r'"\s*,\s*"IDX"\s*\]\s*,.*?,\s*"IDR"\s*,\s*\[\s*([0-9.-]+)'
            )
            fallback_match = re.search(fallback_pattern, html)
            if fallback_match:
                try:
                    result["price"] = float(fallback_match.group(1))
                    result["ok"] = True
                except (ValueError, TypeError) as ve:
                    result["error"] = f"Fallback value conversion error: {ve}"
            else:
                result["error"] = "Data pattern not found in HTML"
                
    except requests.RequestException as e:
        result["error"] = f"Request failed: {e}"
        
    return result


if __name__ == "__main__":
    # Smoke test
    test_tickers = ["TLKM", "BBRI", "BRIS", "PTBA", "ACES"]
    print("=== SMOKE TEST GOOGLE FINANCE SCRAPER ===")
    for tk in test_tickers:
        print(f"Fetching {tk}...")
        res = fetch_google_price(tk)
        print("Result:", res)
        time.sleep(1)
