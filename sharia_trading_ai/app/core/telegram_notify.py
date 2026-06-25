"""
Notifikasi Telegram — kirim ringkasan/alert ke chat via Bot API.

Kredensial dari settings (.env): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
TELEGRAM_ENABLED. Pengiriman dipicu eksplisit oleh pengguna (tombol), bukan
otomatis.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


def is_configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def status() -> dict[str, Any]:
    return {
        "configured": is_configured(),
        "enabled": settings.telegram_enabled,
        "chat_id_set": bool(settings.telegram_chat_id),
    }


def send(text: str) -> dict[str, Any]:
    if not is_configured():
        return {"ok": False, "error": "Telegram belum dikonfigurasi (set TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID di .env)."}
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": settings.telegram_chat_id, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        r = httpx.post(url, json=payload, timeout=15)
        data = r.json()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("description", "gagal kirim")}
        return {"ok": True, "message_id": data["result"].get("message_id")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
