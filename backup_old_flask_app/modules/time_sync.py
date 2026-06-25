"""
Sinkronisasi Waktu Nasional (BMKG / WIB)
========================================
Mengambil waktu acuan dari server NTP nasional Indonesia (ntp.bmkg.go.id) agar
seluruh keputusan waktu aplikasi (jam bursa, jendela koneksi, scheduler-gating)
merujuk ke Waktu Indonesia Barat resmi — bukan sekadar jam sistem yang bisa drift.

Implementasi NTP minimal pakai stdlib (socket/struct), tanpa dependensi eksternal.
Menyimpan OFFSET (waktu_server - waktu_lokal) dan menyegarkannya berkala. Bila NTP
gagal (jaringan/blokir UDP), offset 0 → fallback ke jam sistem (tetap jalan).

API:
    now_utc()  -> datetime tz-aware UTC, terkoreksi offset BMKG
    now_wib()  -> datetime tz-aware WIB (UTC+7)
    sync(force) -> refresh offset, return dict status
    status()   -> info offset & kapan terakhir sync
"""

import logging
import os
import socket
import struct
import threading
import time as _time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("sharia.time_sync")

TZ_WIB = timezone(timedelta(hours=7), name="WIB")

NTP_SERVERS = [
    s.strip() for s in os.environ.get(
        "NTP_SERVERS", "ntp.bmkg.go.id,time.bmkg.go.id"
    ).split(",") if s.strip()
]
NTP_PORT = 123
NTP_TIMEOUT = float(os.environ.get("NTP_TIMEOUT_S", "4"))
# Selisih epoch NTP (1900) vs Unix (1970)
_NTP_UNIX_DELTA = 2208988800
# TTL offset: seberapa sering re-sync (default 30 menit)
SYNC_TTL_S = int(os.environ.get("NTP_SYNC_TTL_S", "1800"))

_lock = threading.Lock()
_state = {"offset": 0.0, "synced_at": 0.0, "server": None, "ok": False}


def _query_ntp(host: str) -> float:
    """Return waktu server (Unix epoch float, UTC) atau raise."""
    pkt = bytearray(48)
    pkt[0] = 0x1B  # LI=0, VN=3, Mode=3 (client)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(NTP_TIMEOUT)
    try:
        s.sendto(bytes(pkt), (host, NTP_PORT))
        data, _ = s.recvfrom(48)
    finally:
        s.close()
    if len(data) < 48:
        raise ValueError("respons NTP terlalu pendek")
    # Transmit Timestamp ada di byte 40..47 (detik 4 byte + fraksi 4 byte)
    secs, frac = struct.unpack("!II", data[40:48])
    return (secs - _NTP_UNIX_DELTA) + frac / 2**32


def sync(force: bool = False) -> dict:
    """Refresh offset dari NTP BMKG bila TTL lewat atau force. Aman dipanggil sering."""
    now_local = _time.time()
    with _lock:
        fresh = (now_local - _state["synced_at"]) < SYNC_TTL_S
        if fresh and not force and _state["ok"]:
            return dict(_state)
    for host in NTP_SERVERS:
        try:
            server_epoch = _query_ntp(host)
            offset = server_epoch - _time.time()
            with _lock:
                _state.update(offset=offset, synced_at=_time.time(), server=host, ok=True)
            logger.info("NTP sync %s ok, offset=%.3fs", host, offset)
            return dict(_state)
        except Exception as e:
            logger.warning("NTP %s gagal: %s", host, e)
    with _lock:
        _state.update(synced_at=_time.time(), ok=False)  # tandai sudah dicoba
    logger.warning("Semua server NTP gagal — pakai jam sistem (offset 0)")
    return dict(_state)


def _offset() -> float:
    # Lazy-sync bila belum pernah / TTL lewat
    if (_time.time() - _state["synced_at"]) >= SYNC_TTL_S or _state["synced_at"] == 0:
        sync()
    return _state["offset"]


def now_utc() -> datetime:
    return datetime.fromtimestamp(_time.time() + _offset(), tz=timezone.utc)


def now_wib() -> datetime:
    return now_utc().astimezone(TZ_WIB)


def status() -> dict:
    st = dict(_state)
    st["age_s"] = int(_time.time() - st["synced_at"]) if st["synced_at"] else None
    st["now_wib"] = now_wib().isoformat()
    st["servers"] = NTP_SERVERS
    return st


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json
    print(json.dumps(sync(force=True), indent=2))
    print(json.dumps(status(), indent=2, default=str))
