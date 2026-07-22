"""
Impor portofolio dari gambar/PDF — ekstraksi via LLM vision (Gemini/Claude).

Pengguna upload screenshot/PDF aplikasi broker (Stockbit/Bibit/Ajaib/IPOT/Mirae/
BIONS, dll). LLM multimodal mengekstrak posisi (ticker, lot, avg, harga, nilai,
P/L) jadi JSON terstruktur, lalu bisa diimpor ke portofolio (P/L live + Decisions).

Engine: Gemini (gemini-2.5-flash, vision) bila GEMINI_API_KEY ada; jika tidak,
Claude bila ANTHROPIC_API_KEY ada.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Optional

import httpx

from app.config import settings

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _f(v: Any) -> Optional[float]:
    """Number-or-None (JSON dari Gemini sudah numerik; string ditangani aman)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("Rp", "").replace(" ", "")
    if not s or s.lower() in ("n/a", "null", "-", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None

PROMPT = """\
Kamu mengekstrak data PORTOFOLIO SAHAM dari screenshot/PDF aplikasi broker Indonesia.
Broker yang sering dipakai pengguna:
  • Profits Anywhere (Phintraco/Profindo Sekuritas) — kolom: Kode/Stock, Lot,
    Avg/Harga Rata-rata, Last/Prev, Market Value, Gain/Loss (Rp & %).
  • Stockbit / Bibit (Stockbit Sekuritas) — kolom: Symbol, Lot, Avg Price, Last,
    Market Value, Floating Gain/Loss (Rp & %), Port %.
Juga bisa: Ajaib, IPOT, Mirae HOTS, BIONS, dll.

Kembalikan HANYA JSON valid:
{
  "broker": "Profits Anywhere" | "Stockbit/Bibit" | nama broker terdeteksi,
  "positions": [
    {"ticker": "ADRO", "lots": 10, "shares": 1000, "avg_price": 2100,
     "last_price": 2240, "value": 2240000, "pl": 140000, "pl_pct": 6.67}
  ],
  "total_value": 0, "total_pl": 0, "total_pl_pct": 0, "catatan": "ringkas"
}

ATURAN PENTING:
- ticker = kode saham BEI (3-5 huruf kapital, mis. ADRO, TLKM, BBRI).
- KONVENSI LOT: di Profits Anywhere & Stockbit/Bibit kolom kuantitas biasanya
  LOT (1 lot = 100 lembar). Jadi lots = angka kuantitas apa adanya, shares = lots×100.
  Hanya jika kolom JELAS bertuliskan "lembar"/"shares", maka lots = lembar / 100.
- avg_price = harga rata-rata beli per LEMBAR; last_price = harga terkini per lembar.
- value = nilai pasar (Rp); pl = untung/rugi (Rp, negatif jika rugi); pl_pct = % (negatif jika rugi).
- Bila angka tidak terlihat, isi null. JANGAN mengarang.
- Abaikan baris non-saham (kas/RDN/saldo/reksadana/total) dari "positions".
Keluarkan JSON saja, tanpa teks/markdown lain."""

_BROKER_NORM = {
    "stockbit": "Stockbit/Bibit", "bibit": "Stockbit/Bibit",
    "profit anywhere": "Profits Anywhere", "profits anywhere": "Profits Anywhere",
    "phintraco": "Profits Anywhere", "profindo": "Profits Anywhere",
    "pluang": "Pluang",
}


def _norm_broker(b: Optional[str]) -> Optional[str]:
    if not b:
        return None
    key = str(b).strip().lower()
    for k, v in _BROKER_NORM.items():
        if k in key:
            return v
    return str(b)


def engine_available() -> Optional[str]:
    return None


def _clean_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _normalize(data: dict[str, Any], broker: Optional[str]) -> dict[str, Any]:
    out = []
    for p in data.get("positions") or []:
        tk = str(p.get("ticker", "")).strip().upper()
        if not tk:
            continue
        lots = _f(p.get("lots"))
        shares = _f(p.get("shares"))
        if lots is None and shares is not None:
            lots = round(shares / 100, 2)
        elif lots is not None and shares is None:
            shares = round(lots * 100)

        avg = _f(p.get("avg_price")) or _f(p.get("harga_rata_rata"))
        val = _f(p.get("value")) or _f(p.get("nilai_pasar"))
        pl = _f(p.get("pl")) or _f(p.get("floating_pl"))
        pl_pct = _f(p.get("pl_pct")) or _f(p.get("floating_pl_pct"))

        # fallback hitung
        if avg and shares and not val:
            val = round(shares * avg)

        out.append({
            "ticker": tk, "lots": lots, "shares": shares, "avg_price": avg,
            "current_price": _f(p.get("last_price")) or avg,
            "value": val, "pl": pl, "pl_pct": pl_pct,
            "broker": broker, "importable": bool(lots and avg),
        })
    return {
        "positions": out,
        "total_value": data.get("total_value"),
        "total_pl": data.get("total_pl"),
        "total_pl_pct": data.get("total_pl_pct"),
        "broker": broker,
        "catatan": data.get("catatan"),
    }


def parse_portfolio(file_bytes: bytes, mime_type: str,
                    broker_hint: Optional[str] = None) -> dict[str, Any]:
    return {"ok": False, "error": "LLM Vision (Gemini/Claude) dinonaktifkan. Gunakan impor berbasis teks/OCR lokal."}
