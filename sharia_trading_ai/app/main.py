"""
Sharia Trading AI — FastAPI web service.

Decision-support untuk trading saham syariah BEI berbasis metodologi
"Sharia Investment and Trading Module" + Fatwa DSN-MUI. Hanya analisa & sinyal
(tidak mengeksekusi order). Bukan ajakan jual/beli — keputusan di tangan Anda.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import SHARIA, TEMPLATES_DIR, settings
from app.routers import accounts, advisor, analysis, extras, learning, plan, portfolio, screening, simulation, undervalue

app = FastAPI(
    title=settings.app_name,
    description=(
        "Decision-support trading saham syariah (BEI) — metodologi CAN SLIM + "
        "6 Magic Number + analisa teknikal, dengan screening Fatwa DSN-MUI. "
        "Advisory only, tanpa eksekusi order."
    ),
    version="1.0.0",
)

app.include_router(screening.router)
app.include_router(analysis.router)
app.include_router(plan.router)
app.include_router(advisor.router)
app.include_router(portfolio.router)
app.include_router(extras.router)
app.include_router(undervalue.router)
app.include_router(accounts.router)
app.include_router(simulation.router)
app.include_router(learning.router)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(TEMPLATES_DIR.parent / "static")), name="static")


@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.on_event("startup")
async def _start_master_scheduler():
    """Rebuild master_data terjadwal (Opsi 1) — agar fundamental tak basi."""
    import asyncio

    hours = settings.master_rebuild_hours
    if not hours or hours <= 0:
        return

    async def _loop():
        from app.data import build_master
        while True:
            await asyncio.sleep(hours * 3600)
            try:
                await asyncio.to_thread(build_master.build)
            except Exception:
                pass

    asyncio.create_task(_loop())


@app.on_event("startup")
async def _start_funnel_watcher():
    """Pemantau Funnel intraday: tiap N menit (jam bursa) → alert Telegram bila ada sinyal baru."""
    import asyncio
    from datetime import datetime, time

    if not settings.funnel_watch_enabled:
        return
    every = max(5, int(settings.funnel_watch_minutes)) * 60

    async def _loop():
        from app.core import reminders, watcher
        await asyncio.sleep(30)                          # beri jeda saat startup
        while True:
            try:
                now = datetime.now()
                # hanya jam bursa: hari bursa & 08:45–16:05 WIB (server-lokal)
                if reminders.is_trading_day(now.date()) and time(8, 45) <= now.time() <= time(16, 5):
                    await asyncio.to_thread(watcher.run_and_alert)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(every)

    asyncio.create_task(_loop())


@app.on_event("startup")
async def _start_reminder_scheduler():
    """Pengingat harian Telegram (pagi: siapkan order · sore: jalankan funnel)."""
    import asyncio
    from datetime import datetime, timedelta

    if not settings.reminder_enabled:
        return

    def _hhmm(s: str):
        try:
            h, m = s.split(":")
            return int(h), int(m)
        except Exception:
            return None

    async def _loop():
        from app.core import reminders
        sent: dict[str, str] = {}                       # kind → tanggal terakhir kirim
        plan = [("morning", settings.reminder_morning), ("evening", settings.reminder_evening)]
        while True:
            await asyncio.sleep(60)
            now = datetime.now()
            today = now.date()
            tomorrow = today + timedelta(days=1)
            for kind, tstr in plan:
                hm = _hhmm(tstr or "")
                if not hm or sent.get(kind) == today.isoformat():
                    continue
                # pagi: hanya hari bursa · sore: hari ini ATAU besok hari bursa
                ok_day = (reminders.is_trading_day(today) if kind == "morning"
                          else reminders.is_trading_day(today) or reminders.is_trading_day(tomorrow))
                if not ok_day:
                    continue
                target = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
                if now >= target:
                    sent[kind] = today.isoformat()       # tandai (hindari spam walau telat)
                    if (now - target).total_seconds() <= 2 * 3600:   # hanya kirim bila ≤2 jam telat
                        try:
                            await asyncio.to_thread(reminders.send_reminder, kind)
                        except Exception:
                            pass

    asyncio.create_task(_loop())


@app.on_event("startup")
async def _start_simulation_scheduler():
    """Simulasi Eksekusi Harian: rekam kartu BUY tiap pagi bursa, evaluasi TP/SL/horizon tiap sore."""
    import asyncio
    from datetime import datetime

    if not settings.simulation_enabled:
        return

    def _hhmm(s: str):
        try:
            h, m = s.split(":")
            return int(h), int(m)
        except Exception:  # noqa: BLE001
            return None

    async def _loop():
        from app.core import reminders, simulation as sim
        done: dict[str, str] = {}                        # kind → tanggal terakhir dijalankan
        plan = [("capture", settings.simulation_capture_time),
                ("evaluate", settings.simulation_evaluate_time)]
        while True:
            await asyncio.sleep(60)
            now = datetime.now()
            today = now.date()
            if not reminders.is_trading_day(today):
                continue
            for kind, tstr in plan:
                hm = _hhmm(tstr or "")
                if not hm or done.get(kind) == today.isoformat():
                    continue
                target = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
                if now >= target:
                    done[kind] = today.isoformat()       # tandai (anti-duplikat walau telat)
                    try:
                        if kind == "capture":
                            await asyncio.to_thread(sim.capture_today)
                        else:
                            await asyncio.to_thread(sim.evaluate_open)
                    except Exception:  # noqa: BLE001
                        pass

    asyncio.create_task(_loop())


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "app": settings.app_name, "mode": settings.trading_mode}


@app.get("/api/disclaimer", tags=["meta"])
def disclaimer():
    return {
        "disclaimer": (
            "Aplikasi ini alat bantu analisa, BUKAN ajakan/rekomendasi jual-beli. "
            "Segala keputusan & risiko investasi sepenuhnya tanggung jawab pengguna. "
            "Past performance bukan jaminan hasil masa depan."
        ),
        "kepatuhan_syariah": SHARIA.PROHIBITED_PRACTICES,
        "acuan": [
            "Fatwa DSN-MUI No. 40/DSN-MUI/X/2003 (Pasar Modal Syariah)",
            "Fatwa DSN-MUI No. 80/DSN-MUI/III/2011 (mekanisme perdagangan ekuitas)",
            "Sharia Investment and Trading Module — Doddy Eka Putra / YLive Academy",
        ],
    }


@app.get("/", response_class=HTMLResponse, tags=["meta"])
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "app_name": settings.app_name})
