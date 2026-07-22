"""
Cache hasil Pusat Keputusan (Funnel) — agar web selalu punya data ≤ N menit.

- Prefetch terjadwal tiap `funnel_cache_minutes` saat jam bursa IDX.
- GET /api/decisions tanpa refresh → pakai cache bila masih segar.
- GET /api/decisions?refresh=true (tombol Jalankan Funnel) → hitung ulang + simpan.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Optional

from app.config import BASE_DIR, settings
from app.core import decisions

CACHE_FILE = BASE_DIR.parent / "data_store" / "decisions_cache.json"
_lock = threading.Lock()
_memory: Optional[dict[str, Any]] = None
_running = False


def _ttl_seconds() -> int:
    return max(5, int(settings.funnel_cache_minutes)) * 60


def _now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Jakarta")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return datetime.now()


def idx_session_active(now: Optional[datetime] = None) -> bool:
    """True pada hari bursa IDX dalam jendela prefetch (pra-buka s/d pasca-tutup singkat)."""
    from datetime import time as _time
    from app.core import reminders

    now = now or _now()
    if not reminders.is_trading_day(now.date()):
        return False
    return _time(8, 45) <= now.time() <= _time(16, 15)


def _stamp(payload: dict[str, Any], *, from_cache: bool) -> dict[str, Any]:
    out = dict(payload)
    meta = out.get("cache") or {}
    generated = meta.get("generated_at") or out.get("generated_at")
    age = None
    if generated:
        try:
            gen = datetime.fromisoformat(str(generated).replace("Z", ""))
            age = max(0, int((_now() - gen).total_seconds()))
        except Exception:  # noqa: BLE001
            age = None
    out["cache"] = {
        "from_cache": from_cache,
        "generated_at": generated,
        "age_seconds": age,
        "ttl_seconds": _ttl_seconds(),
        "fresh": (age is not None and age <= _ttl_seconds()),
        "prefetch_enabled": bool(settings.funnel_cache_enabled),
        "next_hint": (
            f"Cache ≤{settings.funnel_cache_minutes} mnt · "
            "klik ▶ Jalankan Funnel untuk data terbaru"
        ),
    }
    out["generated_at"] = generated
    out["from_cache"] = from_cache
    return out


def _load_disk() -> Optional[dict[str, Any]]:
    try:
        if not CACHE_FILE.exists():
            return None
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "buy" not in data:
            return None
        return data
    except Exception:  # noqa: BLE001
        return None


def _save_disk(payload: dict[str, Any]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Jangan simpan flag from_cache di disk sebagai kebenaran
        to_save = {k: v for k, v in payload.items() if k not in ("from_cache",)}
        CACHE_FILE.write_text(json.dumps(to_save, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def peek() -> Optional[dict[str, Any]]:
    """Baca cache tanpa rebuild (memory → disk)."""
    global _memory
    with _lock:
        if _memory is not None:
            return _stamp(dict(_memory), from_cache=True)
        disk = _load_disk()
        if disk is not None:
            _memory = disk
            return _stamp(dict(disk), from_cache=True)
    return None


def is_fresh(payload: Optional[dict[str, Any]] = None) -> bool:
    data = payload or peek()
    if not data:
        return False
    age = (data.get("cache") or {}).get("age_seconds")
    return age is not None and age <= _ttl_seconds()


def build_fresh(
    limit: int | None = None,
    target: int | None = None,
    force_open: bool | None = None,
) -> dict[str, Any]:
    """Hitung ulang Funnel dan simpan ke cache."""
    global _memory, _running
    with _lock:
        if _running:
            # Hindari dobel-hitung: kembalikan cache lama bila ada
            cached = _memory or _load_disk()
            if cached:
                return _stamp(dict(cached), from_cache=True)
        _running = True
    try:
        raw = decisions.build_decisions(limit=limit, target=target, force_open=force_open)
        generated = _now().isoformat(timespec="seconds")
        raw["generated_at"] = generated
        raw["cache"] = {
            "generated_at": generated,
            "ttl_seconds": _ttl_seconds(),
            "source": "live_build",
        }
        with _lock:
            _memory = raw
            _save_disk(raw)
        return _stamp(dict(raw), from_cache=False)
    finally:
        with _lock:
            _running = False


def get_decisions(
    *,
    refresh: bool = False,
    limit: int | None = None,
    target: int | None = None,
    force_open: bool | None = None,
) -> dict[str, Any]:
    """Ambil keputusan: cache segar, atau rebuild bila refresh/basi/kosong."""
    if not refresh:
        cached = peek()
        if cached and is_fresh(cached):
            return cached
        # Cache basi / kosong — rebuild (juga mengisi prefetch setelah buka web pertama kali)
    return build_fresh(limit=limit, target=target, force_open=force_open)


def prefetch_if_due() -> dict[str, Any]:
    """Dipanggil scheduler: rebuild hanya di jam bursa IDX (atau paksa bila cache kosong)."""
    if not settings.funnel_cache_enabled:
        return {"ok": False, "skipped": "disabled"}
    active = idx_session_active()
    cached = peek()
    if not active and cached and is_fresh(cached):
        return {"ok": True, "skipped": "outside_session", "age": (cached.get("cache") or {}).get("age_seconds")}
    if not active and cached:
        # Di luar jam: jangan spam rebuild; biarkan cache lama
        return {"ok": True, "skipped": "outside_session_stale_ok", "age": (cached.get("cache") or {}).get("age_seconds")}
    if not active and not cached:
        # Belum ada cache sama sekali — bangun sekali agar web tidak kosong
        pass
    elif active and cached and is_fresh(cached):
        return {"ok": True, "skipped": "still_fresh", "age": (cached.get("cache") or {}).get("age_seconds")}

    d = build_fresh()
    return {
        "ok": True,
        "rebuilt": True,
        "generated_at": d.get("generated_at"),
        "buy": len(d.get("buy") or []),
        "hold": len(d.get("hold") or []),
        "sell": len(d.get("sell") or []),
        "session_active": active,
    }


def status() -> dict[str, Any]:
    cached = peek()
    age = (cached.get("cache") or {}).get("age_seconds") if cached else None
    return {
        "enabled": bool(settings.funnel_cache_enabled),
        "ttl_minutes": int(settings.funnel_cache_minutes),
        "session_active": idx_session_active(),
        "has_cache": cached is not None,
        "fresh": is_fresh(cached) if cached else False,
        "age_seconds": age,
        "generated_at": (cached or {}).get("generated_at"),
        "running": _running,
        "buy": len((cached or {}).get("buy") or []) if cached else None,
        "hold": len((cached or {}).get("hold") or []) if cached else None,
        "sell": len((cached or {}).get("sell") or []) if cached else None,
    }
