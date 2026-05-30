#!/usr/bin/env python3
"""
Sharia TA Pipeline Cron Runner
===============================
Menjalankan pipeline Sharia Trading Assistant hanya pada pagi hari (pembukaan)
dan sore hari (penutupan), menghindari overhead background thread 24/7.

Jadwal ideal (WIB):
  - Pagi (08:30 WIB): Rebuild master data (yfinance), alert scan, morning Telegram brief.
  - Sore (16:00 WIB): Alert scan closing, closing Telegram brief, auto-export PDF/XLSX.
"""

import os

# macOS fork-safety — HARUS di-set sebelum import library lain (requests, yfinance,
# multiprocessing) supaya child process tidak crash dengan:
#   "+[NSCharacterSet initialize] may have been in progress in another thread when
#    fork() was called. Crashing instead."
# Idealnya juga di-set di launchd plist (com.shariata.pipeline.plist) — ini backup
# untuk kasus dijalankan manual dari terminal.
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

import sys
import argparse
from datetime import datetime

# Set working directory & PYTHONPATH
SAHAM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SAHAM_DIR)

LOG_PATH = os.path.join(SAHAM_DIR, "logs", "pipeline_cron.log")


def log(msg: str):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{ts}] {msg}"
    print(formatted_msg)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")


def run_morning():
    log("=========================================")
    log("▶ STARTING MORNING PIPELINE (08:30 WIB)")
    log("=========================================")

    # 1. Rebuild Master Data
    log("Step 1: Rebuilding master data from yfinance...")
    try:
        from build_master_data import build_master_csv
        input_file = os.path.join(SAHAM_DIR, "daftar_saham_syariah.csv")
        output_file = os.path.join(SAHAM_DIR, "master_data_syariah.csv")
        build_master_csv(input_file, output_file)
        log("✓ Master data rebuilt successfully.")
    except Exception as e:
        log(f"✗ ERROR rebuilding master data: {e}")

    # 2. Run Alert Scan
    log("Step 2: Running alert scan...")
    try:
        from app import app
        from modules.alerts import run_alert_scan
        with app.app_context():
            result = run_alert_scan(app_test_client=app.test_client())
        log(f"✓ Alert scan completed. Found {result['n_alerts']} alerts.")
    except Exception as e:
        log(f"✗ ERROR running alert scan: {e}")

    # 3. Send Morning Brief to Telegram
    log("Step 3: Sending morning brief to Telegram...")
    try:
        from modules.scheduler import send_morning_brief
        # send_morning_brief secara otomatis memuat app dan test_client
        send_morning_brief()
        log("✓ Morning brief sent to Telegram.")
    except Exception as e:
        log(f"✗ ERROR sending morning brief: {e}")

    log("=========================================")
    log("✓ MORNING PIPELINE COMPLETED")
    log("=========================================\n")


def run_afternoon():
    log("=========================================")
    log("▶ STARTING AFTERNOON PIPELINE (16:00 WIB)")
    log("=========================================")

    # 1. Rebuild Master Data (Closing Prices)
    log("Step 1: Rebuilding master data from Google & Yahoo Finance...")
    try:
        from build_master_data import build_master_csv
        input_file = os.path.join(SAHAM_DIR, "daftar_saham_syariah.csv")
        output_file = os.path.join(SAHAM_DIR, "master_data_syariah.csv")
        build_master_csv(input_file, output_file)
        log("✓ Master data rebuilt successfully.")
    except Exception as e:
        log(f"✗ ERROR rebuilding master data: {e}")

    # 2. Run Alert Scan (Closing Prices)
    log("Step 2: Running afternoon alert scan...")
    try:
        from app import app
        from modules.alerts import run_alert_scan
        with app.app_context():
            result = run_alert_scan(app_test_client=app.test_client())
        log(f"✓ Alert scan completed. Found {result['n_alerts']} alerts.")
    except Exception as e:
        log(f"✗ ERROR running alert scan: {e}")

    # 3. Send Closing Brief to Telegram
    log("Step 3: Sending closing brief to Telegram...")
    try:
        from app import app
        from modules.telegram_notify import TelegramNotifier

        notif = TelegramNotifier()
        if notif.configured:
            client = app.test_client()
            decisions = client.get("/api/decisions").get_json()
            portfolio = client.get("/api/portfolio").get_json() or []

            # Kirim ringkasan keputusan akhir bursa & portofolio ke Telegram
            notif.send_text("🔔 *Sharia TA — Ringkasan Penutupan Bursa*")
            notif.send_decisions(decisions)
            if portfolio:
                notif.send_portfolio_summary(portfolio)
            log("✓ Closing brief sent to Telegram.")
        else:
            log("⚠ Telegram not configured in .env, skipping Telegram notification.")
    except Exception as e:
        log(f"✗ ERROR sending closing brief: {e}")

    # 4. Auto Export Reports (PDF & XLSX)
    log("Step 4: Auto-exporting closing reports...")
    try:
        from app import app
        from modules.export import build_summary, export_pdf, export_xlsx
        client = app.test_client()
        ranking = client.get("/api/all_stocks").get_json().get("stocks", [])
        portfolio = client.get("/api/portfolio").get_json() or []
        alerts_today = client.get("/api/alerts/today").get_json() or []

        summary = build_summary(ranking, portfolio, alerts_today)

        pdf_path = export_pdf(ranking, portfolio, alerts_today, summary)
        xlsx_path = export_xlsx(ranking, portfolio, alerts_today, summary)

        log(f"✓ PDF Report exported to: {pdf_path}")
        log(f"✓ XLSX Report exported to: {xlsx_path}")
    except Exception as e:
        log(f"✗ ERROR exporting reports: {e}")

    log("=========================================")
    log("✓ AFTERNOON PIPELINE COMPLETED")
    log("=========================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sharia TA Pipeline Cron Runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--morning", action="store_true", help="Run the morning pipeline (08:30 WIB)")
    group.add_argument("--afternoon", action="store_true", help="Run the afternoon pipeline (16:00 WIB)")

    args = parser.parse_args()

    if args.morning:
        run_morning()
    elif args.afternoon:
        run_afternoon()
