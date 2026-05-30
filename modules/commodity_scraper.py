import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(BASE_DIR, "cache", "commodity_data.json")
URL = "https://harga-emas.org/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
CACHE_TTL = 15 * 60  # Cache selama 15 menit

def get_commodity_data(force_refresh: bool = False) -> Dict:
    """
    Mengambil data komoditas, emas, dan valas dari harga-emas.org.
    Menerapkan caching JSON lokal selama 15 menit untuk efisiensi.
    """
    if not force_refresh and os.path.exists(CACHE_FILE):
        age = time.time() - os.path.getmtime(CACHE_FILE)
        if age < CACHE_TTL:
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    data = {
        "ok": False,
        "timestamp": "",
        "gold_spot": {},
        "spot_table": [],
        "antam_pegadaian_table": [],
        "ubs_table": [],
        "bi_kurs": [],
        "mandiri_kurs": [],
        "bca_kurs": [],
        "pluang_assets": [],
        "error": None
    }

    try:
        r = requests.get(URL, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            data["error"] = f"HTTP Status {r.status_code}"
            return data
        
        soup = BeautifulSoup(r.text, 'html.parser')
        data["ok"] = True
        
        # Parse timestamp update
        time_el = soup.select_one('[class*="HomePage_title-secondary"]')
        data["timestamp"] = time_el.text.strip() if time_el else time.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Parse Spot Gold Cards (USD & IDR Spot Dunia)
        spot_cards = soup.select('[class*="SpotCard_card"]')
        for card in spot_cards:
            title_el = card.select_one('[class*="SpotCard_title"]')
            title = title_el.text.strip() if title_el else "Unknown Spot"
            
            prices_el = card.select('[class*="SpotCard_item"]')
            items = []
            for pr in prices_el:
                price_val_el = pr.select_one('[class*="SpotCard_price"]')
                change_el = pr.select_one('[class*="SpotCard_positive"], [class*="SpotCard_negative"]')
                unit_el = pr.select_one('[class*="SpotCard_unit"]')
                
                price_val = price_val_el.text.strip() if price_val_el else ""
                change_val = change_el.text.strip() if change_el else ""
                unit_val = unit_el.text.strip() if unit_el else ""
                
                items.append({
                    "price": price_val,
                    "change": change_val,
                    "unit": unit_val.replace("/", "").strip()
                })
            
            if "USD" in title:
                data["gold_spot"]["usd"] = items
            elif "IDR" in title:
                data["gold_spot"]["idr"] = items

        # 2. Parse Pluang Assets
        asset_cards = soup.select('[class*="StockCard_stock-item"]')
        for asset in asset_cards:
            sym_el = asset.select_one('[class*="StockCard_symbol"]')
            comp_el = asset.select_one('[class*="StockCard_company"]')
            pct_el = asset.select_one('[class*="StockCard_percentage"]')
            
            sym = sym_el.text.strip() if sym_el else ""
            comp = comp_el.text.strip() if comp_el else ""
            comp = re.sub(r'\s+', ' ', comp)
            pct = pct_el.text.strip() if pct_el else ""
            
            # Tentukan tipe aset (Logam, Stock AS, Crypto)
            category = "Komoditas"
            if sym in ["GLD", "SLV", "GOLD", "PAXG", "XAUT", "XAUTUSDT-PERP"]:
                category = "Logam / ETF"
            elif sym in ["NVDA", "GOOG", "GOOGL", "AAPL"]:
                category = "Saham AS"
            elif sym in ["BTC", "ETH", "USDT", "BNB"]:
                category = "Kripto"
                
            data["pluang_assets"].append({
                "symbol": sym,
                "name": comp,
                "change_pct": pct,
                "category": category
            })

        # 3. Parse Tables
        tables = soup.find_all('table')
        for idx, table in enumerate(tables):
            parent = table.parent
            title = ""
            
            header_search = parent.find_previous(['p', 'h1', 'h2', 'h3', 'div'], class_=re.compile(r'(SubTitle|title|header)'))
            if header_search:
                title = header_search.text.strip()
            
            th_tags = table.find_all('th')
            th_texts = [th.text.strip() for th in th_tags]
            
            rows = table.find_all('tr')
            
            # Tabel 0: Spot Harga Emas Hari Ini (Satuan, USD, IDR)
            if "USD" in th_texts and "IDR" in th_texts:
                for row in rows[1:]:
                    tds = [td.text.strip() for td in row.find_all(['td', 'th'])]
                    if len(tds) >= 3:
                        data["spot_table"].append({
                            "unit": tds[0],
                            "usd": tds[1],
                            "idr": tds[2]
                        })
            
            # Tabel 1: Antam & Pegadaian
            elif "Antam" in th_texts and "Pegadaian" in th_texts:
                for row in rows[2:]:  # Baris 0 dan 1 adalah subheader
                    tds = [td.text.strip() for td in row.find_all(['td', 'th'])]
                    if len(tds) >= 3:
                        data["antam_pegadaian_table"].append({
                            "gram": tds[0],
                            "antam": tds[1],
                            "pegadaian": tds[2]
                        })
            
            # Tabel 2: UBS Gold
            elif "UBS Gold" in title or "UBS" in "".join(th_texts):
                for row in rows[2:]:  # Baris 0 dan 1 adalah subheader
                    tds = [td.text.strip() for td in row.find_all(['td', 'th'])]
                    if len(tds) >= 3:
                        data["ubs_table"].append({
                            "gram": tds[0],
                            "jual": tds[1],
                            "beli": tds[2]
                        })
            
            # Tabel 3, 4, 5: Kurs Bank
            elif "Kurs Bank Indonesia" in title or "BI" in title:
                for row in rows[1:]:
                    tds = [td.text.strip() for td in row.find_all(['td', 'th'])]
                    if len(tds) >= 3:
                        data["bi_kurs"].append({
                            "kurs": tds[0],
                            "beli": tds[1],
                            "jual": tds[2]
                        })
            elif "Mandiri" in title:
                for row in rows[1:]:
                    tds = [td.text.strip() for td in row.find_all(['td', 'th'])]
                    if len(tds) >= 3:
                        data["mandiri_kurs"].append({
                            "kurs": tds[0],
                            "beli": tds[1],
                            "jual": tds[2]
                        })
            elif "BCA" in title:
                for row in rows[1:]:
                    tds = [td.text.strip() for td in row.find_all(['td', 'th'])]
                    if len(tds) >= 3:
                        data["bca_kurs"].append({
                            "kurs": tds[0],
                            "beli": tds[1],
                            "jual": tds[2]
                        })

        # Save to cache
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        data["error"] = f"Failed scraping: {e}"

    return data

if __name__ == "__main__":
    print("Fetching commodity data...")
    res = get_commodity_data(force_refresh=True)
    print("Success:", res["ok"])
    print("Update Time:", res["timestamp"])
    print("Spot Gold:", res["gold_spot"])
    print("Assets Count:", len(res["pluang_assets"]))
    print("Antam/Pegadaian rows:", len(res["antam_pegadaian_table"]))
    print("UBS rows:", len(res["ubs_table"]))
    print("BI Kurs rows:", len(res["bi_kurs"]))
