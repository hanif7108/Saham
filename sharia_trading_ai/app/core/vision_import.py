"""
Impor portofolio dari gambar/PDF — ekstraksi via LLM vision (Gemini/Claude).

Pengguna upload screenshot/PDF aplikasi broker (Stockbit/Bibit/Ajaib/IPOT/Mirae/
BIONS, dll). LLM multimodal mengekstrak posisi (ticker, lot, avg, harga, nilai,
P/L) jadi JSON terstruktur, lalu bisa diimpor ke portofolio (P/L live + Decisions).

Engine: Gemini (gemini-2.5-flash, vision) bila GEMINI_API_KEY ada; jika tidak,
Claude bila ANTHROPIC_API_KEY ada. Ollama gemma4 = teks-only (tidak dipakai).
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
}


def _norm_broker(b: Optional[str]) -> Optional[str]:
    if not b:
        return None
    key = str(b).strip().lower()
    for k, v in _BROKER_NORM.items():
        if k in key:
            return v
    return str(b).strip()


def engine_available() -> Optional[str]:
    if settings.gemini_api_key or os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    return None


def _clean_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def _normalize(data: dict[str, Any], broker: Optional[str]) -> dict[str, Any]:
    out = []
    for p in (data.get("positions") or []):
        tk = str(p.get("ticker") or "").strip().upper()
        if not tk or not re.match(r"^[A-Z]{3,5}$", tk):
            continue
        lots = p.get("lots")
        if lots is None and p.get("shares"):
            try:
                lots = round(float(p["shares"]) / 100)
            except Exception:
                lots = None
        shares = (lots or 0) * 100
        avg = _f(p.get("avg_price"))
        last, pl, val = _f(p.get("last_price")), _f(p.get("pl")), _f(p.get("value"))
        # Derivasi avg bila tak terbaca: dari (value-pl) atau (last - pl/shares)
        derived = False
        if avg is None and shares:
            if val is not None and pl is not None:
                avg, derived = round((val - pl) / shares), True
            elif last is not None and pl is not None:
                avg, derived = round(last - pl / shares), True
        out.append({
            "ticker": tk, "lots": lots, "shares": p.get("shares") or shares or None,
            "avg_price": avg, "avg_derived": derived, "last_price": last,
            "value": val, "pl": pl, "pl_pct": p.get("pl_pct"),
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
    eng = engine_available()
    if eng is None:
        return {"ok": False, "error": "Butuh GEMINI_API_KEY (atau ANTHROPIC_API_KEY) untuk membaca gambar/PDF."}
    if mime_type == "application/pdf" and len(file_bytes) > 18_000_000:
        return {"ok": False, "error": "PDF terlalu besar (>18MB)."}

    prompt = PROMPT
    if broker_hint:
        prompt += f"\nPetunjuk: screenshot ini dari broker {broker_hint}."

    try:
        if eng == "gemini":
            data = _gemini(file_bytes, mime_type, prompt)
        else:
            data = _claude(file_bytes, mime_type, prompt)
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"Gagal memanggil {eng}: {e}"}
    except (json.JSONDecodeError, ValueError):
        return {"ok": False, "error": f"{eng} tidak mengembalikan data terstruktur — coba gambar lebih jelas."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}

    broker = _norm_broker(data.get("broker")) or _norm_broker(broker_hint)
    result = _normalize(data, broker)
    result["ok"] = True
    result["engine"] = eng
    return result


def _gemini(file_bytes: bytes, mime_type: str, prompt: str) -> dict[str, Any]:
    key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
    b64 = base64.b64encode(file_bytes).decode()
    payload = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": mime_type, "data": b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048,
                             "responseMimeType": "application/json",
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    url = f"{GEMINI_BASE}/{settings.gemini_model}:generateContent"
    r = httpx.post(url, params={"key": key}, json=payload, timeout=90)
    d = r.json()
    if r.status_code != 200:
        raise httpx.HTTPError((d.get("error") or {}).get("message", f"HTTP {r.status_code}"))
    parts = (d.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    return _clean_json(text)


def _claude(file_bytes: bytes, mime_type: str, prompt: str) -> dict[str, Any]:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"))
    b64 = base64.b64encode(file_bytes).decode()
    if mime_type == "application/pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    else:
        block = {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}}
    resp = client.messages.create(
        model=settings.ai_model, max_tokens=2048,
        messages=[{"role": "user", "content": [block, {"type": "text", "text": prompt}]}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return _clean_json(text)
