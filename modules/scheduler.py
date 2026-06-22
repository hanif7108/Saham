"""
Scheduler untuk auto-update master data
=======================================
Pakai APScheduler BackgroundScheduler. Idle saat Flask run di main thread.

Default jadwal:
  - 06:00 WIB setiap hari kerja: rebuild master data (build_master_data.py)
  - Tiap 30 menit (jam pasar 09:00–16:00 WIB): refresh harga top tickers
"""

import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import Callable, Optional

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

# Awareness sesi & libur IDX (kalender libur nasional + Sesi 1/Jeda/Sesi 2).
# Kalau modul belum ada (versi lama tanpa patch), fallback ke "selalu open"
# untuk kompatibilitas mundur.
try:
    from modules.market_hours import is_market_open, is_trading_day, is_connectivity_window
except Exception:  # pragma: no cover
    def is_market_open() -> bool:  # type: ignore
        return True

    def is_trading_day(_d=None) -> bool:  # type: ignore
        return True

    def is_connectivity_window(now=None) -> bool:  # type: ignore
        return True


LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "logs",
    "scheduler.log"
)


# Logger mirror: log ke file scheduler.log + stderr (agar muncul juga di
# gunicorn_error.log / launchd_stderr.log untuk observability terpusat).
logger = logging.getLogger("sharia.scheduler")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger.propagate = False


def _log(msg: str):
    """Backward-compat wrapper. Tulis ke scheduler.log + stderr via logger."""
    logger.info(msg)


SAHAM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_build_master():
    """Run build_master_data.py sebagai subprocess (skip otomatis di hari libur)."""
    if not is_trading_day():
        _log("Skip build_master: hari ini libur/weekend (tidak ada data IDX baru).")
        return
    _log("Starting build_master_data.py")
    try:
        # Pakai sys.executable (bukan 'python3' dari PATH) agar mengikuti venv yang
        # me-run scheduler ini — penting saat dijalankan via launchd dengan PATH minimal.
        proc = subprocess.Popen(
            [sys.executable, os.path.join(SAHAM_DIR, "build_master_data.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=SAHAM_DIR,
        )
        # Tidak block — biarkan jalan di background
        _log(f"build_master started PID={proc.pid}")
    except Exception as e:
        _log(f"build_master ERROR: {e}")


def send_morning_brief():
    """Pre-market brief setiap jam 08:45 WIB ke Telegram.

    Pakai send_dashboard_summary (8-section terstruktur) — lebih kaya daripada
    send_decisions + send_portfolio_summary terpisah. Include alokasi 4-bucket,
    action plan IDX+US dengan sizing, top 5 IDX+US, komoditas, alert.
    """
    try:
        sys.path.insert(0, SAHAM_DIR)
        from app import app
        from modules.telegram_notify import TelegramNotifier

        notif = TelegramNotifier()
        if not notif.configured:
            _log("Morning brief skipped: Telegram not configured")
            return

        client = app.test_client()
        dashboard = client.get("/api/dashboard").get_json() or {}
        # US data (opsional — kalau master US belum di-build, akan None)
        us_action_plan = None
        us_top5 = None
        try:
            us_action_plan = client.get("/api/us/action_plan").get_json()
            us_top5 = (client.get("/api/us/top5").get_json() or {}).get("data")
        except Exception as ue:
            _log(f"Morning brief: US data unavailable ({ue})")

        result = notif.send_dashboard_summary(
            dashboard=dashboard,
            us_action_plan=us_action_plan,
            us_top5=us_top5,
        )
        if result.get("ok"):
            _log("Morning brief (dashboard summary) sent to Telegram")
        else:
            _log(f"Morning brief send failed: {result}")
    except Exception as e:
        _log(f"Morning brief FAILED: {e}")


def send_morning_boost_alert():
    """Morning boost alert setiap jam 09:02 WIB ke Telegram (Breakout/Breaker)."""
    try:
        import sys
        sys.path.insert(0, SAHAM_DIR)
        from app import app
        from modules.telegram_notify import TelegramNotifier
        
        notif = TelegramNotifier()
        if not notif.configured:
            return
            
        client = app.test_client()
        decisions = client.get("/api/decisions").get_json() or {}
        buys = decisions.get("buy", [])
        
        # Cari emiten syariah dengan pola breaker atau strong setup aktif
        breaker_buys = [b for b in buys if b.get("urgency") == "HIGH" or "breaker" in b.get("reason", "").lower()]
        
        if not breaker_buys:
            text = (
                "🚀 *Jalur 7% — Morning Boost Alert (09:02 WIB)*\n\n"
                "Pasar telah dibuka. Tidak terdeteksi setup breakout / Breaker yang cukup kuat pagi ini.\n"
                "_Disarankan Wait & See atau pantau watchlist lainnya._"
            )
        else:
            lines = [
                "🚀 *Jalur 7% — Morning Boost Alert (09:02 WIB)*\n",
                "Pasar telah dibuka. Berikut emiten syariah potensial untuk entry breakout/momentum pagi ini:\n"
            ]
            for b in breaker_buys[:3]:
                lines.append(
                    f" • *{b.get('ticker')}* — {b.get('reason')}\n"
                    f"   👉 _Saran:_ {b.get('next_step')}\n"
                )
            lines.append("\n_Aturan: Jaga batasan risiko max 2% dan pasang Stop Loss!_")
            text = "\n".join(lines)
            
        notif.send_text(text)
        _log("Morning boost alert sent to Telegram")
    except Exception as e:
        _log(f"Morning boost alert FAILED: {e}")


def send_midday_brief():
    """Mid-day review sesi I perdagangan (Mon-Thu 12:05 WIB / Fri 11:35 WIB)."""
    try:
        import sys
        sys.path.insert(0, SAHAM_DIR)
        from app import app
        from modules.telegram_notify import TelegramNotifier
        
        notif = TelegramNotifier()
        if not notif.configured:
            return
            
        client = app.test_client()
        portfolio = client.get("/api/portfolio").get_json() or []
        
        if not portfolio:
            text = (
                "⏸ *Jalur 7% — Istirahat Sesi I*\n\n"
                "Sesi I perdagangan telah ditutup.\n"
                "Portofolio aktif Anda kosong saat ini.\n"
                "Evaluasi kembali rencana trading Anda untuk Sesi II."
            )
        else:
            lines = [
                "⏸ *Jalur 7% — Istirahat Sesi I*\n",
                "Sesi I perdagangan telah ditutup. Berikut status portofolio aktif Anda:\n"
            ]
            for p in portfolio:
                pnl = p.get("pnl", 0) or 0
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(
                    f" • {emoji} *{p.get('ticker')}* — PnL: *{pnl:+.2f}%* "
                    f"(Harga Beli: {p.get('harga_beli',0):,.0f} | Harga Sekarang: {p.get('current_price',0):,.0f})"
                )
            text = "\n".join(lines)
            
        notif.send_text(text)
        _log("Midday brief sent to Telegram")
    except Exception as e:
        _log(f"Midday brief FAILED: {e}")


def send_closing_push_alert():
    """Closing push alert setiap jam 14:45 WIB ke Telegram (Kandang Kuda/Shadow)."""
    try:
        import sys
        sys.path.insert(0, SAHAM_DIR)
        from app import app
        from modules.telegram_notify import TelegramNotifier
        
        notif = TelegramNotifier()
        if not notif.configured:
            return
            
        client = app.test_client()
        decisions = client.get("/api/decisions").get_json() or {}
        buys = decisions.get("buy", [])
        
        # Cari saham konsolidasi dekat MA20 (Kandang Kuda/Shadow)
        consol_buys = [b for b in buys if any(kw in b.get("reason", "").lower() for kw in ["kandang kuda", "shadow", "dca", "speculative"])]
        
        if not consol_buys:
            text = (
                "⚡ *Jalur 7% — Closing Push Alert (14:45 WIB)*\n\n"
                "Menjelang penutupan pasar. Tidak ditemukan saham konsolidasi sehat atau defending support di dekat MA20.\n"
                "_Disarankan menahan diri untuk entry sore ini._"
            )
        else:
            lines = [
                "⚡ *Jalur 7% — Closing Push Alert (14:45 WIB)*\n",
                "Menjelang penutupan pasar. Berikut emiten syariah konsolidasi dekat MA20 untuk akumulasi sore ini:\n"
            ]
            for b in consol_buys[:3]:
                lines.append(
                    f" • *{b.get('ticker')}* — {b.get('reason')}\n"
                    f"   👉 _Saran:_ {b.get('next_step')}\n"
                )
            lines.append("\n_Aturan: Beli di menit-menit akhir (14:50-15:00) jika struktur & volume tetap stabil._")
            text = "\n".join(lines)
            
        notif.send_text(text)
        _log("Closing push alert sent to Telegram")
    except Exception as e:
        _log(f"Closing push alert FAILED: {e}")


def start_scheduler(refresh_callback: Optional[Callable] = None):
    """Start background scheduler. Aman dipanggil meski APScheduler tidak terinstall."""
    if not APSCHEDULER_AVAILABLE:
        _log("APScheduler not available — skipping scheduler init")
        return None

    scheduler = BackgroundScheduler(timezone="Asia/Jakarta")

    # Tiap 06:00 WIB Senin–Jumat: rebuild master data
    scheduler.add_job(
        run_build_master,
        CronTrigger(hour=6, minute=0, day_of_week="mon-fri"),
        id="daily_master_rebuild",
        replace_existing=True
    )

    # Tiap 08:45 WIB Senin–Jumat: Pre-Market Screening ke Telegram
    scheduler.add_job(
        send_morning_brief,
        CronTrigger(hour=8, minute=45, day_of_week="mon-fri"),
        id="morning_brief_telegram",
        replace_existing=True
    )

    # Tiap 09:02 WIB Senin–Jumat: Morning Boost (window breakout)
    scheduler.add_job(
        send_morning_boost_alert,
        CronTrigger(hour=9, minute=2, day_of_week="mon-fri"),
        id="morning_boost_telegram",
        replace_existing=True
    )

    # Tiap 12:05 WIB Senin-Kamis: Mid-day Sesi I
    scheduler.add_job(
        send_midday_brief,
        CronTrigger(hour=12, minute=5, day_of_week="mon-thu"),
        id="midday_brief_mon_thu",
        replace_existing=True
    )

    # Tiap 11:35 WIB Jumat: Mid-day Sesi I (Jumat)
    scheduler.add_job(
        send_midday_brief,
        CronTrigger(hour=11, minute=35, day_of_week="fri"),
        id="midday_brief_fri",
        replace_existing=True
    )

    # Tiap 14:45 WIB Senin–Jumat: Closing Push (window akumulasi sore)
    scheduler.add_job(
        send_closing_push_alert,
        CronTrigger(hour=14, minute=45, day_of_week="mon-fri"),
        id="closing_push_telegram",
        replace_existing=True
    )

    # Intraday alert scan — interval sesuai TRADING_MODE
    try:
        from modules.trading_mode import get_scan_interval_min
        interval = get_scan_interval_min()  # 5 (scalping) | 30 (swing) | 60 (position)
    except Exception:
        interval = 30

    def auto_alert_scan():
        """Run alert scan + push ke Telegram kalau ada hit.

        Gating: skip silent saat pasar tutup (jeda 11:30–13:30 / Fri 11:30–14:00,
        sebelum 09:00, setelah 16:15, weekend, atau hari libur nasional).
        Override testing via env FORCE_MARKET_OPEN=1.
        """
        if not is_market_open():
            # Skip diam-diam — tidak perlu spam log. Cukup di-trace level debug.
            logger.debug("auto_alert_scan skipped: market closed")
            return
        try:
            sys.path.insert(0, SAHAM_DIR)
            from app import app
            from modules.alerts import run_alert_scan
            with app.app_context():
                result = run_alert_scan(app_test_client=app.test_client())
            _log(f"Auto alert scan: {result['n_alerts']} alerts, types={result['by_type']}")
        except Exception as e:
            _log(f"Auto alert scan FAILED: {e}")

    scheduler.add_job(
        auto_alert_scan,
        CronTrigger(minute=f"*/{interval}", hour="9-15", day_of_week="mon-fri"),
        id="intraday_alert_scan",
        replace_existing=True
    )
    _log(f"Intraday alert scan setiap {interval} menit (mode-aware)")

    # Collector intraday TradingView — enrich harga saat jam bursa IDX.
    # Polling serial ~3 mnt/15 simbol → jalankan tiap 5 menit, gate jam bursa di dalam.
    # Dimatikan via env TV_COLLECTOR_ENABLED=0.
    if os.environ.get("TV_COLLECTOR_ENABLED", "1").strip() not in {"0", "false", "no"}:
        try:
            tv_interval = int(os.environ.get("TV_POLL_INTERVAL_MIN", "5"))
        except ValueError:
            tv_interval = 5

        def tv_intraday_poll():
            if not is_connectivity_window():
                logger.debug("tv_intraday_poll skipped: di luar jendela koneksi")
                return
            try:
                from modules.tv_collector import poll_and_store
                result = poll_and_store()
                _log(f"TV intraday poll: {result}")
            except Exception as e:
                _log(f"TV intraday poll FAILED: {e}")

        scheduler.add_job(
            tv_intraday_poll,
            CronTrigger(minute=f"*/{tv_interval}", hour="7-17", day_of_week="mon-fri"),
            id="tv_intraday_poll",
            replace_existing=True,
            max_instances=1,  # cegah tumpang-tindih bila 1 siklus > interval
            coalesce=True,
        )
        _log(f"TV intraday collector setiap {tv_interval} menit (jam bursa)")

    # Narasi AI terjadwal (Claude API) — lingkup holding, cadence lambat (mahal).
    # Aktif hanya bila ANTHROPIC_API_KEY ada; dimatikan via AI_NARRATIVE_ENABLED=0.
    if os.environ.get("AI_NARRATIVE_ENABLED", "1").strip() not in {"0", "false", "no"}:
        try:
            ai_interval = int(os.environ.get("AI_NARRATIVE_INTERVAL_MIN", "30"))
        except ValueError:
            ai_interval = 30

        def ai_narrative_run():
            if not is_connectivity_window():
                return
            try:
                from modules.ai_narrative import generate_and_store
                result = generate_and_store()
                if result.get("status") != "no_api_key":
                    _log(f"AI narrative: {result}")
            except Exception as e:
                _log(f"AI narrative FAILED: {e}")

        scheduler.add_job(
            ai_narrative_run,
            CronTrigger(minute=f"*/{ai_interval}", hour="7-17", day_of_week="mon-fri"),
            id="ai_narrative",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _log(f"AI narrative setiap {ai_interval} menit (jam bursa, bila API key ada)")

    # Hook lama untuk refresh callback (kalau dipanggil eksternal)
    if refresh_callback is not None:
        scheduler.add_job(
            refresh_callback,
            CronTrigger(minute="*/30", hour="9-15", day_of_week="mon-fri"),
            id="intraday_refresh",
            replace_existing=True
        )

    scheduler.start()
    _log("Scheduler started")
    return scheduler
