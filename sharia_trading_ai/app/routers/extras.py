"""Endpoint tambahan — komoditas/Dinar, alert, Telegram."""

from __future__ import annotations

from fastapi import APIRouter

from fastapi import HTTPException

from app.config import settings
from app.core import alerts, bei_calendar, commodities, decisions, dividend, funnel_cache, reminders, telegram_notify, watcher
from app.data import build_master
from app.models.schemas import DividendIn, HolidayIn, TelegramSendIn

router = APIRouter(prefix="/api", tags=["extras"])


@router.get("/decisions")
def get_decisions(limit: int | None = None, target: int | None = None,
                  force_open: bool | None = None, refresh: bool = False):
    """Pusat Keputusan portfolio-aware dgn strategi N-emiten terkonsentrasi.

    - `target`     = jumlah emiten yang dijaga (default config = 3).
    - `force_open` = Mode Uji: paksa sinyal penuh walau bursa libur (pengembangan).
    - `refresh`    = True → hitung ulang sekarang (tombol Jalankan Funnel).
                     False → pakai cache prefetch bila masih ≤ funnel_cache_minutes.
    """
    return funnel_cache.get_decisions(
        refresh=refresh, limit=limit, target=target, force_open=force_open,
    )


@router.get("/datalake/status")
def datalake_status():
    """Status sinkronisasi Datalake NAS (ditulis scripts/datalake_sync.sh)."""
    import json
    from app.config import BASE_DIR
    state = BASE_DIR.parent / "ml_data" / "datalake_state.json"
    base = {"nas": "100.70.97.42", "remote": "/share/CACHEDEV1_DATA/DataLake/saham-syariah",
            "schedule": "harian 17:05 WIB (launchd com.shariata.datalake_sync)"}
    try:
        return {**base, **json.loads(state.read_text())}
    except Exception:
        return {**base, "last_status": "belum pernah sync",
                "last_message": "pasang SSH key dulu: ssh-copy-id qnap@100.70.97.42"}


@router.get("/portfolio/review")
def portfolio_review():
    """Posisi milik + vonis exit + ML + ROI bulanan (utk dashboard)."""
    from app.core import portfolio_snapshot
    out = portfolio_snapshot.build_review()
    out["monthly_roi"] = portfolio_snapshot.monthly_roi()
    return out


@router.get("/ml/focus")
def ml_focus(refresh: bool = False):
    """Dua tahap: top-10 screening konvensional -> dinilai model ML screened."""
    from app.core import ml_signal
    return ml_signal.focus_top10(force=refresh)


@router.get("/ml/signals")
def ml_signals(refresh: bool = False):
    """Prediksi ML seluruh universe IDX (cache 15 mnt) — untuk panel dashboard."""
    from app.core import ml_signal
    return ml_signal.scan_universe(force=refresh)


@router.get("/ml/track")
def ml_track_record():
    """Track record sinyal ML: prediksi vs realisasi + kalibrasi ambang."""
    from app.ml import tracker
    return tracker.summary_for_api()


@router.get("/decisions/cache")
def decisions_cache_status():
    """Status cache Funnel periodik (umur, TTL, jam bursa)."""
    return funnel_cache.status()


@router.get("/market/status")
def market_status():
    """Status bursa IDX (BEI) + US (NYSE) — jam sesi & tren ringkas."""
    idx = decisions.market_status()
    us = decisions.market_status_us()
    return {"idx": idx, "us": us}


@router.get("/market/holidays")
def market_holidays():
    """Kalender Hari Libur Bursa BEI: libur berikutnya + daftar mendatang."""
    return {"next": bei_calendar.next_holiday(), "upcoming": bei_calendar.upcoming(),
            "all": bei_calendar.holidays(), "source": bei_calendar.source()}


@router.post("/market/holidays")
def add_holiday(h: HolidayIn):
    """Tambah/ubah hari libur bursa kustom (mis. suspensi/cuti tambahan)."""
    try:
        return bei_calendar.add_holiday(h.date, h.name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal harus YYYY-MM-DD.")


@router.delete("/market/holidays/{tanggal}")
def delete_holiday(tanggal: str):
    if not bei_calendar.remove_holiday(tanggal):
        raise HTTPException(status_code=404, detail="tanggal tidak ada di kalender")
    return {"ok": True, "deleted": tanggal}


@router.get("/master/status")
def master_status():
    return build_master.status()


@router.post("/master/rebuild")
def master_rebuild(limit: int | None = None):
    """Bangun ulang master_data_syariah.csv dari yfinance (fundamental terbaru)."""
    return build_master.build(limit=limit)


@router.get("/commodities")
def get_commodities():
    """Emas, perak, minyak, kurs + Dinar/Dirham (IDR)."""
    return commodities.commodities()


@router.get("/alerts")
def get_alerts():
    """Pindai peluang entry & status portofolio."""
    return alerts.build_alerts()


@router.get("/telegram/status")
def telegram_status():
    return telegram_notify.status()


@router.post("/telegram/send")
def telegram_send(req: TelegramSendIn):
    """Kirim teks (atau ringkasan alert bila kosong) ke Telegram."""
    text = req.text
    if not text:
        text = alerts.format_message(alerts.build_alerts())
    return telegram_notify.send(text)


@router.get("/dividend/{ticker}")
def dividend_info(ticker: str):
    """Profil dividen 1 saham: rutinitas, yield, ex-date terakhir, &amp; dividen mendatang."""
    return dividend.profile(ticker)


@router.post("/dividend/refresh/{ticker}")
def dividend_refresh(ticker: str):
    """Ambil ulang data dividen dari web (stockevents/yfinance) — bypass cache."""
    dividend.refresh(ticker)
    return dividend.profile(ticker)


@router.post("/dividend/calendar")
def dividend_set(d: DividendIn):
    """Catat cum-date/ex-date &amp; nominal dividen yang sudah diumumkan (presisi)."""
    try:
        return dividend.set_event(d.ticker, d.ex_date, d.amount, d.rups_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format tanggal harus YYYY-MM-DD.")


@router.delete("/dividend/calendar/{ticker}")
def dividend_del(ticker: str):
    if not dividend.remove_event(ticker):
        raise HTTPException(status_code=404, detail="ticker tidak ada di kalender dividen")
    return {"ok": True, "deleted": ticker.upper()}


@router.get("/funnel-watch/status")
def funnel_watch_status():
    """Status pemantau Funnel intraday."""
    import json as _json
    from app.core.watcher import STATE
    st = {}
    try:
        st = _json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        pass
    return {"enabled": settings.funnel_watch_enabled, "minutes": settings.funnel_watch_minutes,
            "min_conviction": settings.funnel_watch_min_conviction,
            "telegram": telegram_notify.status(), "state": st,
            "catatan": "Jalan tiap N menit pada jam bursa (08:45–16:05 WIB). Kirim Telegram hanya bila ada sinyal BARU & signifikan."}


@router.post("/funnel-watch/run")
def funnel_watch_run(force: bool = False):
    """Jalankan pemantau sekarang (uji). force=true → kirim walau sudah pernah dialert hari ini."""
    return watcher.run_and_alert(force=force)


@router.get("/reminders/status")
def reminders_status():
    """Status pengingat harian Telegram (pagi/sore) + apakah hari ini hari bursa."""
    from datetime import date
    return {
        "enabled": settings.reminder_enabled,
        "morning": settings.reminder_morning, "evening": settings.reminder_evening,
        "telegram": telegram_notify.status(),
        "today_trading_day": reminders.is_trading_day(date.today()),
        "catatan": "Waktu server-lokal (set mesin ke WIB). Pagi hanya hari bursa; "
                   "sore bila hari ini/besok hari bursa. Butuh Telegram terkonfigurasi & server aktif.",
    }


@router.post("/reminders/test")
def reminders_test(kind: str = "evening"):
    """Kirim pengingat contoh sekarang (kind=morning|evening) untuk uji."""
    return reminders.send_reminder("morning" if kind == "morning" else "evening")


@router.get("/reminders/preview")
def reminders_preview(kind: str = "evening"):
    """Pratinjau teks pengingat (tanpa kirim) — untuk lihat isi rencana."""
    return {"kind": kind, "text": reminders.build_plan_text("morning" if kind == "morning" else "evening")}
