"""Endpoint Advisor — narasi analisa. Engine: Claude / Gemini / Ollama / Lokal."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.core import (
    ai_advisor,
    funnel,
    gemini_advisor,
    local_advisor,
    ollama_advisor,
)

router = APIRouter(prefix="/api", tags=["advisor"])


def _auto_engine() -> str:
    if ai_advisor.is_enabled():
        return "claude"
    if gemini_advisor.is_enabled():
        return "gemini"
    if ollama_advisor.is_available():
        return "ollama"
    return "lokal"


@router.get("/advisor/status")
def advisor_status():
    """Engine yang tersedia & default (auto)."""
    return {
        "default": _auto_engine(),
        "engines": {
            "claude": {"tersedia": ai_advisor.is_enabled(), "biaya": "berbayar (~$0.02-0.03)",
                       "model": settings.ai_model},
            "gemini": {"tersedia": gemini_advisor.is_enabled(), "biaya": "gratis (free tier, ada kuota)",
                       "model": settings.gemini_model},
            "ollama": {"tersedia": ollama_advisor.is_available(), "biaya": "gratis (lokal)",
                       "model": settings.ollama_model, "models": ollama_advisor.available_models()},
            "lokal": {"tersedia": True, "biaya": "gratis (instan, berbasis aturan)"},
        },
    }


@router.get("/advisor/{ticker}")
def advisor(ticker: str, engine: str = "auto"):
    """
    engine: auto | claude | gemini | ollama | lokal
      auto  → Claude (key) → Gemini (key) → Ollama (lokal) → Lokal aturan.
      gemini→ Google Gemini (free tier, cepat) · butuh GEMINI_API_KEY.
      ollama→ LLM lokal gratis (gemma4) · lambat tapi privat & tanpa biaya.
      lokal → berbasis aturan, instan, gratis.
    """
    report = funnel.analyze_stock(ticker)
    eng = _auto_engine() if engine == "auto" else engine

    if eng == "claude" and ai_advisor.is_enabled():
        result = ai_advisor.advise(report)
    elif eng == "gemini":
        result = gemini_advisor.advise(report)
        if result.get("error"):                       # Gemini gagal → fallback aturan
            result = local_advisor.advise(report)
            result["fallback_dari"] = "gemini"
    elif eng == "ollama":
        result = ollama_advisor.advise(report)
        if result.get("enabled") is False or result.get("error"):  # Ollama mati/gagal → fallback
            result = local_advisor.advise(report)
            result["fallback_dari"] = "ollama"
    else:
        result = local_advisor.advise(report)

    result["ticker"] = ticker.upper()
    result["engine"] = eng
    result["rekomendasi_mesin"] = report.get("rekomendasi")
    return result
