"""
Advisor via DeepSeek (API OpenAI-compatible).

Aktif bila DEEPSEEK_API_KEY di-set. Memakai system prompt & format yang sama
dengan Gemini/Claude (`ai_advisor.SYSTEM_PROMPT`). Model default: deepseek-chat.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from app.config import settings
from app.core.ai_advisor import SYSTEM_PROMPT, _format_report, _split_verdict

BASE_URL = "https://api.deepseek.com/v1/chat/completions"


def _key() -> str:
    return (settings.deepseek_api_key or os.getenv("DEEPSEEK_API_KEY", "")).strip()


def is_enabled() -> bool:
    return bool(_key())


def _call_deepseek(
    system: str,
    user: str,
    *,
    max_tokens: int = 1500,
    temperature: float = 0.4,
) -> dict[str, Any]:
    """Panggil DeepSeek chat/completions. Return {ok, text, usage} atau {ok:False, error}."""
    key = _key()
    if not key:
        return {"ok": False, "error": "DEEPSEEK_API_KEY belum di-set."}

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    t0 = time.time()
    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(BASE_URL, json=payload, headers=headers)
        if resp.status_code == 401:
            return {"ok": False, "error": "DeepSeek: API key tidak valid (401)."}
        if resp.status_code == 402:
            return {"ok": False, "error": "DeepSeek: saldo/kuota habis (402)."}
        if resp.status_code == 429:
            return {"ok": False, "error": "DeepSeek: rate limit (429) — coba lagi sebentar."}
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = (resp.json().get("error") or {}).get("message") or resp.text[:200]
            except Exception:  # noqa: BLE001
                detail = resp.text[:200]
            return {"ok": False, "error": f"DeepSeek HTTP {resp.status_code}: {detail}"}

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return {"ok": False, "error": "DeepSeek: respons kosong."}
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not text:
            return {"ok": False, "error": "DeepSeek: teks kosong."}
        usage = data.get("usage") or {}
        return {
            "ok": True,
            "text": text,
            "usage": {
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "durasi_detik": round(time.time() - t0, 1),
            },
        }
    except httpx.TimeoutException:
        return {"ok": False, "error": "DeepSeek timeout."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Gagal memanggil DeepSeek: {e}"}


def advise(report: dict[str, Any]) -> dict[str, Any]:
    if not is_enabled():
        return {
            "enabled": False,
            "message": (
                "DeepSeek nonaktif. Set DEEPSEEK_API_KEY di .env "
                "(platform.deepseek.com), lalu restart server."
            ),
        }

    res = _call_deepseek(SYSTEM_PROMPT, _format_report(report))
    if not res.get("ok"):
        return {"enabled": True, "error": res.get("error", "DeepSeek gagal.")}

    text = res["text"]
    analisa, verdict = _split_verdict(text)
    if isinstance(verdict, dict) and "rekomendasi" in verdict and "rekomendasi_claude" not in verdict:
        verdict = {**verdict, "rekomendasi_claude": verdict.get("rekomendasi")}

    return {
        "enabled": True,
        "model": f"DeepSeek · {settings.deepseek_model}",
        "analisa": analisa or text,
        "verdict": verdict,
        "usage": res.get("usage") or {},
    }


def explain(prompt: str) -> dict[str, Any]:
    """Penjelasan singkat indikator (untuk /advisor/explain)."""
    if not is_enabled():
        return {"enabled": False, "error": "DeepSeek nonaktif."}
    system = (
        "Anda adalah asisten analis saham Syariah BEI yang handal, ringkas, dan to-the-point. "
        "Jawab dalam Bahasa Indonesia, maks 150 kata, tanpa basa-basi."
    )
    res = _call_deepseek(system, prompt, max_tokens=400, temperature=0.3)
    if not res.get("ok"):
        return {"enabled": True, "error": res.get("error")}
    return {
        "enabled": True,
        "model": f"DeepSeek · {settings.deepseek_model}",
        "explanation": res["text"],
        "usage": res.get("usage") or {},
    }
