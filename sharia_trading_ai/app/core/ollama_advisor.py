"""
Advisor via Ollama (LLM lokal GRATIS) — mis. gemma4 di komputer pengguna.

Memakai system prompt & format data yang sama dengan AI Advisor (Claude), tapi
inferensi berjalan lokal di Ollama (http://localhost:11434) — tanpa biaya API.
Lebih lambat dari cloud (bisa 1-2 menit) namun privat & gratis.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.core.ai_advisor import SYSTEM_PROMPT, _format_report


def is_available() -> bool:
    """Cek server Ollama hidup dan model tersedia."""
    try:
        r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3)
        if r.status_code != 200:
            return False
        names = [m.get("name", "") for m in r.json().get("models", [])]
        base = settings.ollama_model.split(":")[0]
        return any(n == settings.ollama_model or n.split(":")[0] == base for n in names)
    except Exception:
        return False


def available_models() -> list[str]:
    try:
        r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []


def advise(report: dict[str, Any]) -> dict[str, Any]:
    if not is_available():
        return {"enabled": False,
                "message": f"Ollama tidak tersedia di {settings.ollama_base_url} "
                           f"atau model '{settings.ollama_model}' belum ada."}
    payload = {
        "model": settings.ollama_model,
        "think": False,  # gemma4 = model thinking; matikan agar token tidak habis utk reasoning
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _format_report(report)},
        ],
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": 1100},
    }
    try:
        r = httpx.post(f"{settings.ollama_base_url}/api/chat", json=payload, timeout=240)
        data = r.json()
        text = (data.get("message") or {}).get("content", "").strip()
        if not text:
            return {"enabled": True, "error": "Ollama mengembalikan respons kosong."}
        return {
            "enabled": True,
            "model": f"Ollama · {settings.ollama_model} (lokal, gratis)",
            "analisa": text,
            "usage": {"output_tokens": data.get("eval_count"),
                      "durasi_detik": round((data.get("total_duration") or 0) / 1e9, 1)},
        }
    except httpx.TimeoutException:
        return {"enabled": True, "error": "Ollama timeout (model lokal lambat — coba lagi atau pakai engine lokal/instant)."}
    except Exception as e:  # noqa: BLE001
        return {"enabled": True, "error": f"Gagal memanggil Ollama: {e}"}
