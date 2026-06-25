"""
Advisor via Google Gemini (ada free tier di Google AI Studio).

Memakai system prompt & format data yang sama dengan engine lain, lewat REST API
`generativelanguage.googleapis.com` (tanpa SDK tambahan). Aktif bila GEMINI_API_KEY
di-set. Free tier: model flash (mis. gemini-2.0-flash) gratis dengan kuota harian.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.config import settings
from app.core.ai_advisor import SYSTEM_PROMPT, _format_report

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _key() -> str:
    return settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")


def is_enabled() -> bool:
    return bool(_key())


def advise(report: dict[str, Any]) -> dict[str, Any]:
    key = _key()
    if not key:
        return {"enabled": False,
                "message": "Gemini nonaktif. Set GEMINI_API_KEY di .env "
                           "(dapatkan gratis di aistudio.google.com), lalu restart server."}
    url = f"{BASE}/{settings.gemini_model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": _format_report(report)}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 1500,
            # model 2.5 = thinking → matikan agar token tak habis utk reasoning & lebih cepat
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        r = httpx.post(url, params={"key": key}, json=payload, timeout=60)
        data = r.json()
        if r.status_code != 200:
            err = (data.get("error") or {}).get("message", f"HTTP {r.status_code}")
            return {"enabled": True, "error": f"Gemini: {err}"}
        cands = data.get("candidates") or []
        if not cands:
            fb = (data.get("promptFeedback") or {}).get("blockReason")
            return {"enabled": True, "error": f"Gemini tidak mengembalikan jawaban{f' (diblokir: {fb})' if fb else ''}."}
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            return {"enabled": True, "error": "Gemini mengembalikan respons kosong."}
        usage = data.get("usageMetadata") or {}
        return {
            "enabled": True,
            "model": f"Gemini · {settings.gemini_model} (free tier)",
            "analisa": text,
            "usage": {"output_tokens": usage.get("candidatesTokenCount"),
                      "input_tokens": usage.get("promptTokenCount")},
        }
    except httpx.TimeoutException:
        return {"enabled": True, "error": "Gemini timeout."}
    except Exception as e:  # noqa: BLE001
        return {"enabled": True, "error": f"Gagal memanggil Gemini: {e}"}
