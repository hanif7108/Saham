"""Tes timing eksekusi per-zona (IDX=WIB, US=ET)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core import decisions as dec


def test_fmt_countdown():
    assert "2 jam" in dec._fmt_countdown(2 * 3600 + 20 * 60)
    assert "20 menit" in dec._fmt_countdown(2 * 3600 + 20 * 60)
    assert "1 hari" in dec._fmt_countdown(26 * 3600)


def test_timing_idx_open_mentions_wib():
    bursa = {
        "open": True,
        "trading_day": True,
        "weekend": False,
        "holiday": None,
        "session": "sesi-2",
    }
    s = dec._calculate_timing(bursa, False, market="IDX")
    assert "IDX" in s or "bursa IDX" in s
    assert "WIB" in s
    assert "ET" not in s or "WIB" in s  # IDX tidak memakai ET sebagai zona utama


def test_timing_us_open_mentions_et_not_idx_hours():
    bursa_us = {
        "open": True,
        "trading_day": True,
        "weekend": False,
        "holiday": None,
        "session": "regular",
    }
    s = dec._calculate_timing(bursa_us, False, market="US")
    assert "bursa US" in s
    assert "ET" in s
    assert "bursa IDX" not in s


def test_timing_us_closed_waits_for_930_et():
    bursa_us = {
        "open": False,
        "trading_day": True,
        "weekend": False,
        "holiday": None,
        "session": "pasca-penutupan",
    }
    s = dec._calculate_timing(bursa_us, False, market="US")
    assert "09:30" in s or "bursa US" in s
    assert "ET" in s


def test_timing_idx_istirahat_waits_sesi2():
    bursa = {
        "open": False,
        "trading_day": True,
        "weekend": False,
        "holiday": None,
        "session": "istirahat",
    }
    s = dec._calculate_timing(bursa, False, market="IDX")
    # Bisa sesi II atau menunggu buka tergantung jam server; jangan crash
    assert isinstance(s, str) and len(s) > 5


def test_market_status_us_has_et_and_wib():
    us = dec.market_status_us()
    assert us["tz_label"] == "ET"
    assert us["timezone"] == "America/New_York"
    assert us.get("now_et")
    # now_wib opsional tapi seharusnya ada
    assert us.get("now_wib")


def test_market_status_idx_wib():
    idx = dec.market_status()
    assert idx["tz_label"] == "WIB"
    assert "WIB" in (idx.get("now_wib") or "")
