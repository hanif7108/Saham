"""
IDX Market Hours & Holiday Calendar
====================================
Helper terpusat untuk menentukan status sesi Bursa Efek Indonesia (IDX/BEI).

Jam perdagangan resmi IDX (WIB / UTC+7):

  Senin – Kamis
    Sesi 1  : 09:00 – 12:00
    Jeda    : 12:00 – 13:30
    Sesi 2  : 13:30 – 15:49:59
    Pre-close: 15:50 – 16:00:59
    Post    : 16:01 – 16:15

  Jumat
    Sesi 1  : 09:00 – 11:30
    Jeda    : 11:30 – 14:00
    Sesi 2  : 14:00 – 15:49:59
    Pre-close: 15:50 – 16:00:59
    Post    : 16:01 – 16:15

Kalender libur nasional & libur bursa juga dihandle di sini (HUT RI, Lebaran,
Natal, dll). Update IDX_HOLIDAYS_YYYY setiap tahun sesuai SE BEI.

Override testing:
    FORCE_MARKET_OPEN=1 → bypass jam/hari, anggap pasar selalu buka.

API publik:
    is_trading_day(d=None)        -> bool
    is_market_open(now=None)      -> bool   (True saat di sesi 1 / sesi 2)
    current_session_name(now=None) -> str   "SESI_1" | "JEDA" | "SESI_2" |
                                            "PRE_CLOSING" | "POST_TRADING" |
                                            "TUTUP" | "LIBUR" | "WEEKEND"
    market_status(now=None)       -> dict  payload lengkap untuk API
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

# WIB = UTC+7 (Asia/Jakarta tidak punya DST)
TZ_WIB = timezone(timedelta(hours=7), name="WIB")


# -------------------- Kalender Libur Bursa -------------------- #

# Sumber: SE BEI + Kalender Libur Nasional Indonesia.
# Update setiap tahun sesuai pengumuman resmi BEI.
#
# Format: set of date strings "YYYY-MM-DD".

IDX_HOLIDAYS_2026 = {
    # Libur nasional + cuti bersama 2026 (perkiraan; verifikasi dengan SE BEI)
    "2026-01-01",  # Tahun Baru Masehi
    "2026-01-29",  # Tahun Baru Imlek 2577 Kongzili
    "2026-03-19",  # Hari Suci Nyepi (Tahun Baru Saka 1948)
    "2026-03-20",  # Cuti bersama Nyepi
    "2026-04-03",  # Wafat Isa Almasih (Good Friday)
    "2026-04-05",  # Paskah (jatuh Minggu — info)
    "2026-04-14",  # Isra Mikraj Nabi Muhammad
    "2026-05-01",  # Hari Buruh Internasional
    "2026-05-14",  # Kenaikan Isa Almasih
    "2026-05-21",  # Idul Fitri 1447 H (hari ke-1)  (perkiraan; cek SE BEI final)
    "2026-05-22",  # Idul Fitri 1447 H (hari ke-2)
    "2026-05-25",  # Cuti bersama Idul Fitri
    "2026-05-26",  # Cuti bersama Idul Fitri
    "2026-06-01",  # Hari Lahir Pancasila
    "2026-06-01",  # Hari Raya Waisak (perkiraan)
    "2026-07-27",  # Idul Adha 1447 H (perkiraan)
    "2026-08-17",  # HUT Kemerdekaan RI
    "2026-08-17",  # Tahun Baru Islam 1448 H (perkiraan; cek SE BEI)
    "2026-10-26",  # Maulid Nabi Muhammad (perkiraan)
    "2026-12-24",  # Cuti bersama Natal
    "2026-12-25",  # Natal
    # Hari terakhir bursa (biasanya akhir Desember) sering libur — cek SE BEI.
}

IDX_HOLIDAYS_2027 = {
    "2027-01-01",  # Tahun Baru Masehi (placeholder — update saat SE BEI 2027 rilis)
    "2027-08-17",  # HUT Kemerdekaan RI
    "2027-12-25",  # Natal
}

# Gabungkan semua tahun yang dikenal
IDX_HOLIDAYS_ALL = IDX_HOLIDAYS_2026 | IDX_HOLIDAYS_2027


# -------------------- Time helpers -------------------- #

def _now_wib() -> datetime:
    """Sekarang dalam timezone WIB (UTC+7), merujuk waktu nasional BMKG.

    Memakai modules.time_sync (NTP ntp.bmkg.go.id) agar keputusan jam bursa tidak
    bergantung pada jam sistem yang bisa drift. Fallback ke jam sistem bila modul
    time_sync tak tersedia atau NTP gagal (offset 0).
    """
    try:
        from modules.time_sync import now_wib as _bmkg_now_wib
        return _bmkg_now_wib()
    except Exception:
        return datetime.now(timezone.utc).astimezone(TZ_WIB)


def _to_wib(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return _now_wib()
    if dt.tzinfo is None:
        # Anggap WIB
        return dt.replace(tzinfo=TZ_WIB)
    return dt.astimezone(TZ_WIB)


def _force_open() -> bool:
    return os.environ.get("FORCE_MARKET_OPEN", "").strip() in {"1", "true", "TRUE", "yes"}


# -------------------- Public API -------------------- #

def is_trading_day(d: Optional[date] = None) -> bool:
    """True jika tanggal ini hari kerja (Senin–Jumat) dan bukan libur nasional."""
    if _force_open():
        return True
    if d is None:
        d = _now_wib().date()
    if d.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    if d.isoformat() in IDX_HOLIDAYS_ALL:
        return False
    return True


def _session_bounds(d: date):
    """
    Return tuple ((sesi1_start, sesi1_end), (sesi2_start, sesi2_end), pre_close_end)
    untuk tanggal d (handle Senin–Kamis vs Jumat).
    """
    if d.weekday() == 4:  # Jumat
        s1 = (time(9, 0, 0), time(11, 30, 0))
        s2 = (time(14, 0, 0), time(15, 49, 59))
    else:  # Senin–Kamis
        s1 = (time(9, 0, 0), time(12, 0, 0))
        s2 = (time(13, 30, 0), time(15, 49, 59))
    pre_close_end = time(16, 0, 59)
    post_end = time(16, 15, 0)
    return s1, s2, pre_close_end, post_end


def current_session_name(now: Optional[datetime] = None) -> str:
    """
    Klasifikasi sesi saat ini:
      SESI_1 | JEDA | SESI_2 | PRE_CLOSING | POST_TRADING | TUTUP | LIBUR | WEEKEND
    """
    if _force_open():
        return "SESI_1"

    n = _to_wib(now)
    d = n.date()
    t = n.time()

    if d.weekday() >= 5:
        return "WEEKEND"
    if d.isoformat() in IDX_HOLIDAYS_ALL:
        return "LIBUR"

    s1, s2, pre_close_end, post_end = _session_bounds(d)

    # Pre-market (sebelum 09:00) atau setelah post (>16:15) → TUTUP
    if t < s1[0]:
        return "TUTUP"
    if s1[0] <= t <= s1[1]:
        return "SESI_1"
    if s1[1] < t < s2[0]:
        return "JEDA"
    if s2[0] <= t <= s2[1]:
        return "SESI_2"
    # 15:50–16:00
    if time(15, 50, 0) <= t <= pre_close_end:
        return "PRE_CLOSING"
    # 16:01–16:15
    if time(16, 1, 0) <= t <= post_end:
        return "POST_TRADING"
    return "TUTUP"


def is_market_open(now: Optional[datetime] = None) -> bool:
    """
    True jika bursa sedang aktif untuk transaksi (Sesi 1 atau Sesi 2).
    Tidak termasuk pre-closing, post-trading, atau jeda.
    """
    if _force_open():
        return True
    return current_session_name(now) in {"SESI_1", "SESI_2"}


# Menit buffer sebelum buka & sesudah tutup untuk interkoneksi eksternal.
CONNECTIVITY_BUFFER_MIN = int(os.environ.get("CONNECTIVITY_BUFFER_MIN", "60"))


def is_connectivity_window(now: Optional[datetime] = None) -> bool:
    """
    True bila waktu sekarang berada dalam jendela interkoneksi eksternal
    (TradingView / Claude): mulai CONNECTIVITY_BUFFER_MIN menit SEBELUM bursa buka
    s/d CONNECTIVITY_BUFFER_MIN menit SESUDAH bursa tutup (akhir post-trading),
    pada hari bursa saja. Default buffer 60 menit → ~08:00–17:15 WIB.

    Dipakai untuk membatasi poll TradingView & panggilan Claude hanya di sekitar
    jam bursa, bukan sepanjang hari.
    """
    if _force_open():
        return True
    n = _to_wib(now)
    if not is_trading_day(n.date()):
        return False
    s1, s2, pre_close_end, post_end = _session_bounds(n.date())
    buf = timedelta(minutes=CONNECTIVITY_BUFFER_MIN)
    base = n.date()
    open_dt = datetime.combine(base, s1[0], tzinfo=TZ_WIB) - buf
    close_dt = datetime.combine(base, post_end, tzinfo=TZ_WIB) + buf
    return open_dt <= n <= close_dt


def is_trading_window(now: Optional[datetime] = None) -> bool:
    """
    True jika dalam jam perdagangan termasuk pre-closing & post-trading
    (mis. untuk scheduling alert scan terakhir setelah pasar tutup).
    """
    if _force_open():
        return True
    return current_session_name(now) in {
        "SESI_1", "SESI_2", "PRE_CLOSING", "POST_TRADING"
    }


def next_session_change(now: Optional[datetime] = None) -> Optional[datetime]:
    """
    Estimasi waktu perubahan sesi berikutnya (WIB).
    Berguna untuk UI countdown.
    """
    n = _to_wib(now)
    d = n.date()
    t = n.time()

    if d.weekday() >= 5 or d.isoformat() in IDX_HOLIDAYS_ALL:
        # Cari hari kerja berikutnya jam 09:00
        d2 = d + timedelta(days=1)
        while not is_trading_day(d2):
            d2 += timedelta(days=1)
        return datetime.combine(d2, time(9, 0), tzinfo=TZ_WIB)

    s1, s2, pre_close_end, post_end = _session_bounds(d)
    transitions = [s1[0], s1[1], s2[0], s2[1], time(15, 50), post_end]
    for tr in transitions:
        if t < tr:
            return datetime.combine(d, tr, tzinfo=TZ_WIB)
    # Setelah pasar tutup → besok 09:00
    d2 = d + timedelta(days=1)
    while not is_trading_day(d2):
        d2 += timedelta(days=1)
    return datetime.combine(d2, time(9, 0), tzinfo=TZ_WIB)


def market_status(now: Optional[datetime] = None) -> dict:
    """
    Payload status pasar lengkap untuk API/UI.
    """
    n = _to_wib(now)
    session = current_session_name(n)
    open_ = is_market_open(n)

    badge = "TUTUP"
    if session in {"SESI_1", "SESI_2"}:
        badge = "BUKA"
    elif session == "JEDA":
        badge = "JEDA"
    elif session == "PRE_CLOSING":
        badge = "PRE-CLOSE"
    elif session == "POST_TRADING":
        badge = "POST"
    elif session == "LIBUR":
        badge = "LIBUR"
    elif session == "WEEKEND":
        badge = "WEEKEND"

    next_change = next_session_change(n)

    return {
        "now_wib": n.isoformat(timespec="seconds"),
        "is_market_open": open_,
        "is_trading_day": is_trading_day(n.date()),
        "session": session,
        "badge": badge,
        "next_change_wib": next_change.isoformat(timespec="seconds") if next_change else None,
        "force_market_open": _force_open(),
    }


# -------------------- Backward-compat helper -------------------- #
# modules/cache.py lama memakai nama is_idx_market_open(). Tetap export agar
# import lama tidak putus.

def is_idx_market_open() -> bool:
    return is_market_open()


# ==================================================================== #
# US MARKET HOURS (NYSE / NASDAQ)                                       #
# ==================================================================== #
# NYSE & NASDAQ jam reguler: 09:30 – 16:00 ET (Eastern Time).
# Pre-market : 04:00 – 09:30 ET
# After-hours: 16:00 – 20:00 ET
#
# Note: US punya DST (Daylight Saving Time). Implementasi sederhana di sini
# pakai UTC offset bertahap berdasarkan bulan (akurat ±1 minggu di transisi
# DST — cukup untuk gating algoritmik, BUKAN untuk timestamping kritis).
# DST aktif: Maret minggu ke-2 → November minggu ke-1.

US_HOLIDAYS_2026 = {
    "2026-01-01",   # New Year's Day
    "2026-01-19",   # MLK Jr. Day (3rd Mon of Jan)
    "2026-02-16",   # Washington's Birthday (3rd Mon of Feb)
    "2026-04-03",   # Good Friday
    "2026-05-25",   # Memorial Day (last Mon of May)
    "2026-06-19",   # Juneteenth
    "2026-07-03",   # Independence Day observed (Jul 4 is Sat)
    "2026-09-07",   # Labor Day (1st Mon of Sep)
    "2026-11-26",   # Thanksgiving (4th Thu of Nov)
    "2026-12-25",   # Christmas Day
}

US_HOLIDAYS_2027 = {
    "2027-01-01",
    "2027-01-18",
    "2027-02-15",
    "2027-03-26",
    "2027-05-31",
    "2027-06-18",
    "2027-07-05",   # Jul 4 is Sunday → observed Mon
    "2027-09-06",
    "2027-11-25",
    "2027-12-24",   # Dec 25 is Sat → observed Fri
}

US_HOLIDAYS_ALL = US_HOLIDAYS_2026 | US_HOLIDAYS_2027


def _is_us_dst(d: date) -> bool:
    """Approximate: DST aktif 2nd Sunday March – 1st Sunday November."""
    # Cari 2nd Sunday of March
    march = date(d.year, 3, 1)
    # weekday: Mon=0..Sun=6
    days_to_sunday = (6 - march.weekday()) % 7
    second_sunday_march = date(d.year, 3, 1 + days_to_sunday + 7)
    # Cari 1st Sunday of November
    nov = date(d.year, 11, 1)
    days_to_sunday = (6 - nov.weekday()) % 7
    first_sunday_nov = date(d.year, 11, 1 + days_to_sunday)
    return second_sunday_march <= d < first_sunday_nov


def _us_tz_offset_hours(d: date) -> int:
    """ET offset dari UTC: EST=-5, EDT=-4."""
    return -4 if _is_us_dst(d) else -5


def _now_et() -> datetime:
    """Sekarang dalam timezone Eastern Time (akurat ±1 minggu di DST transition)."""
    now_utc = datetime.now(timezone.utc)
    offset = _us_tz_offset_hours(now_utc.date())
    return now_utc.astimezone(timezone(timedelta(hours=offset), name="ET"))


def is_us_trading_day(d: Optional[date] = None) -> bool:
    if os.environ.get("FORCE_US_MARKET_OPEN", "") in {"1", "true", "TRUE"}:
        return True
    if d is None:
        d = _now_et().date()
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in US_HOLIDAYS_ALL


def is_us_market_open(now: Optional[datetime] = None) -> bool:
    """True jika NYSE/NASDAQ session reguler (09:30 – 16:00 ET)."""
    if os.environ.get("FORCE_US_MARKET_OPEN", "") in {"1", "true", "TRUE"}:
        return True
    n = now or _now_et()
    if n.tzinfo is None:
        # Anggap input sudah ET
        pass
    elif n.utcoffset() != timedelta(hours=_us_tz_offset_hours(n.date())):
        # Convert ke ET
        offset = _us_tz_offset_hours(n.date())
        n = n.astimezone(timezone(timedelta(hours=offset), name="ET"))
    if not is_us_trading_day(n.date()):
        return False
    t = n.time()
    return time(9, 30) <= t <= time(16, 0)


def us_current_session_name(now: Optional[datetime] = None) -> str:
    """
    PRE_MARKET (04:00-09:30) | REGULAR (09:30-16:00) | AFTER_HOURS (16:00-20:00) |
    CLOSED | WEEKEND | HOLIDAY
    """
    if os.environ.get("FORCE_US_MARKET_OPEN", "") in {"1", "true", "TRUE"}:
        return "REGULAR"
    n = now or _now_et()
    d = n.date()
    if d.weekday() >= 5:
        return "WEEKEND"
    if d.isoformat() in US_HOLIDAYS_ALL:
        return "HOLIDAY"
    t = n.time()
    if time(4, 0) <= t < time(9, 30):
        return "PRE_MARKET"
    if time(9, 30) <= t <= time(16, 0):
        return "REGULAR"
    if time(16, 0) < t <= time(20, 0):
        return "AFTER_HOURS"
    return "CLOSED"


def us_market_status(now: Optional[datetime] = None) -> dict:
    """Payload status NYSE/NASDAQ untuk API/UI."""
    n = now or _now_et()
    session = us_current_session_name(n)
    open_ = is_us_market_open(n)
    badge = {
        "PRE_MARKET": "PRE",
        "REGULAR": "BUKA",
        "AFTER_HOURS": "AFTER",
        "CLOSED": "TUTUP",
        "WEEKEND": "WEEKEND",
        "HOLIDAY": "LIBUR",
    }.get(session, "?")
    return {
        "now_et": n.isoformat(timespec="seconds"),
        "now_wib": n.astimezone(TZ_WIB).isoformat(timespec="seconds"),
        "is_market_open": open_,
        "is_trading_day": is_us_trading_day(n.date()),
        "session": session,
        "badge": badge,
        "dst_active": _is_us_dst(n.date()),
    }
