"""Tes cache Funnel periodik (tanpa jaringan / tanpa build penuh)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from app.core import funnel_cache as fc


def test_stamp_marks_from_cache():
    payload = {
        "buy": [], "hold": [], "sell": [],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cache": {"generated_at": datetime.now().isoformat(timespec="seconds")},
    }
    out = fc._stamp(payload, from_cache=True)
    assert out["from_cache"] is True
    assert out["cache"]["from_cache"] is True
    assert out["cache"]["fresh"] is True


def test_is_fresh_respects_ttl():
    old = datetime.now() - timedelta(minutes=45)
    stale = {
        "buy": [],
        "cache": {"generated_at": old.isoformat(timespec="seconds"), "age_seconds": 45 * 60},
    }
    # _stamp menghitung age ulang
    stamped = fc._stamp(
        {"buy": [], "generated_at": old.isoformat(timespec="seconds"),
         "cache": {"generated_at": old.isoformat(timespec="seconds")}},
        from_cache=True,
    )
    assert stamped["cache"]["fresh"] is False


def test_get_decisions_uses_cache_when_fresh():
    fresh_at = datetime.now().isoformat(timespec="seconds")
    cached = {
        "buy": [{"ticker": "AAAA"}],
        "hold": [],
        "sell": [],
        "jumlah": {"buy": 1, "hold": 0, "sell": 0},
        "generated_at": fresh_at,
        "cache": {"generated_at": fresh_at},
    }
    with patch.object(fc, "peek", return_value=fc._stamp(cached, from_cache=True)), \
         patch.object(fc, "build_fresh") as build:
        out = fc.get_decisions(refresh=False)
        build.assert_not_called()
        assert out["from_cache"] is True
        assert out["buy"][0]["ticker"] == "AAAA"


def test_get_decisions_refresh_forces_build():
    with patch.object(fc, "build_fresh", return_value={
        "buy": [], "hold": [], "sell": [], "from_cache": False,
        "generated_at": "2026-01-01T00:00:00",
        "cache": {"from_cache": False},
    }) as build:
        out = fc.get_decisions(refresh=True)
        build.assert_called_once()
        assert out["from_cache"] is False


def test_idx_session_active_weekend_false():
    # Sabtu
    sat = datetime(2026, 7, 18, 10, 0)  # Saturday
    with patch("app.core.reminders.is_trading_day", return_value=False):
        assert fc.idx_session_active(sat) is False
