#!/usr/bin/env python3
"""
Runner script for Sharia Trading Assistant Scheduler.
Jalan 24 jam untuk mengirimkan alert dan briefing otomatis ke Telegram.
"""
import os

# macOS fork-safety — set SEBELUM import library lain (apscheduler, requests,
# yfinance) supaya thread/subprocess yang di-spawn scheduler tidak crash dengan:
#   "+[NSCharacterSet initialize] may have been in progress in another thread when
#    fork() was called. Crashing instead."
# Backup untuk kasus run_scheduler.py dijalankan di luar konteks gunicorn.
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

import sys
import time
import signal

# Tambahkan working directory ke path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Load .env manual agar seluruh modul membaca environment variables yang sama
def load_dotenv():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        print(f"[scheduler] Loading configuration from {env_path}")
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v

load_dotenv()

from modules.scheduler import start_scheduler

def handle_sigterm(signum, frame):
    print("[scheduler] SIGTERM/SIGINT received, exiting gracefully...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    print("[scheduler] Starting background scheduler...")
    sched = start_scheduler()
    
    if sched is None:
        print("[scheduler] ERROR: Scheduler could not be started (APScheduler not installed?)")
        sys.exit(1)
        
    print("[scheduler] Scheduler is running. Press Ctrl+C to stop.")
    
    # Loop keep-alive
    try:
        while True:
            time.sleep(1)
    except SystemExit:
        pass
