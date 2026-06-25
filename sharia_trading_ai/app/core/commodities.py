"""
Emas, Perak, Komoditas & unit moneter Islam (Dinar/Dirham).

Sumber: yfinance — GC=F (emas USD/oz), SI=F (perak USD/oz), CL=F (minyak WTI
USD/bbl), IDR=X (kurs USD/IDR). Harga emas/perak dikonversi ke IDR per gram,
lalu Dinar (4.25 g emas 22k) & Dirham (2.975 g perak murni).

Catatan: ini harga SPOT pasar global (estimasi). Emas fisik (Antam/Pegadaian)
punya premium. Jual-beli emas/perak syariah harus tunai & serah-terima (taqabudh).
"""

from __future__ import annotations

from typing import Any, Optional

from app.data import provider

TROY_OZ_G = 31.1034768
DINAR_GRAM = 4.25      # 1 dinar = 4.25 g emas 22 karat
DIRHAM_GRAM = 2.975    # 1 dirham = 2.975 g perak murni
KARAT_22 = 22 / 24


def _last_change(symbol: str) -> tuple[Optional[float], Optional[float]]:
    try:
        df = provider.get_history(symbol, period="1mo")
        if df is None or df.empty or len(df) < 2:
            return None, None
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        return round(last, 2), round((last - prev) / prev * 100, 2)
    except Exception:
        return None, None


def _item(nama: str, harga: Optional[float], unit: str, chg: Optional[float],
          syariah: str = "") -> dict[str, Any]:
    return {"nama": nama, "harga": harga, "unit": unit, "change_pct": chg, "syariah": syariah}


def commodities() -> dict[str, Any]:
    gold_usd, gold_chg = _last_change("GC=F")
    silver_usd, silver_chg = _last_change("SI=F")
    oil_usd, oil_chg = _last_change("CL=F")
    usdidr, usdidr_chg = _last_change("IDR=X")

    gold_idr_g = round(gold_usd / TROY_OZ_G * usdidr) if (gold_usd and usdidr) else None
    silver_idr_g = round(silver_usd / TROY_OZ_G * usdidr) if (silver_usd and usdidr) else None
    dinar = round(DINAR_GRAM * (gold_idr_g or 0) * KARAT_22) if gold_idr_g else None
    dirham = round(DIRHAM_GRAM * silver_idr_g) if silver_idr_g else None

    return {
        "emas_komoditas": [
            _item("Emas (spot)", gold_usd, "USD/oz", gold_chg, "Permissible (tunai/taqabudh)"),
            _item("Emas (IDR)", gold_idr_g, "IDR/gram 24k", gold_chg),
            _item("Minyak WTI", oil_usd, "USD/barrel", oil_chg),
            _item("Kurs USD/IDR", usdidr, "IDR", usdidr_chg),
        ],
        "perak_dinar": [
            _item("Perak (spot)", silver_usd, "USD/oz", silver_chg, "Permissible (tunai/taqabudh)"),
            _item("Perak (IDR)", silver_idr_g, "IDR/gram", silver_chg),
            _item("Dinar Emas", dinar, "IDR · 4.25g 22k", gold_chg, "Unit moneter Islam"),
            _item("Dirham Perak", dirham, "IDR · 2.975g", silver_chg, "Unit moneter Islam"),
        ],
        "catatan": (
            "Harga spot global (estimasi) — emas fisik (Antam/Pegadaian) memiliki premium. "
            "Transaksi emas/perak syariah wajib tunai & serah-terima seketika (taqabudh), "
            "tanpa riba."
        ),
    }
