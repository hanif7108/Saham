#!/usr/bin/env python3
import os
import sys
import datetime
import subprocess
from zoneinfo import ZoneInfo

SAHAM_DIR = "/Users/hanif/Saham"
STATE_DIR = os.path.join(SAHAM_DIR, "state")
PID_FILE = os.path.join(STATE_DIR, "caffeinate.pid")
LOG_FILE = os.path.join(SAHAM_DIR, "logs", "caffeinate_manager.log")

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{timestamp}] {message}"
    print(msg)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass

def is_pid_running_caffeinate(pid):
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "comm="], text=True)
        return "caffeinate" in out.lower()
    except Exception:
        return False

def get_current_pid():
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return None

def save_pid(pid):
    try:
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, "w") as f:
            f.write(str(pid))
    except Exception as e:
        log(f"Error saving PID file: {e}")

def remove_pid_file():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception as e:
        log(f"Error removing PID file: {e}")

def main():
    # Resolve current time in Jakarta
    tz = ZoneInfo("Asia/Jakarta")
    now = datetime.datetime.now(tz)
    
    # Check if weekday (0 = Monday, 4 = Friday)
    is_weekday = now.weekday() < 5
    
    # Gating: 07:00 WIB to 18:00 WIB
    start_time = now.replace(hour=7, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=18, minute=0, second=0, microsecond=0)
    
    is_active_window = is_weekday and (start_time <= now < end_time)
    
    running_pid = get_current_pid()
    caffeinate_active = False
    if running_pid:
        if is_pid_running_caffeinate(running_pid):
            caffeinate_active = True
        else:
            log("Stale PID file found. Process is not running or not caffeinate.")
            remove_pid_file()
            running_pid = None
            
    if is_active_window:
        if caffeinate_active:
            pass
        else:
            # Calculate remaining seconds until 18:00 WIB
            remaining_seconds = int((end_time - now).total_seconds())
            if remaining_seconds > 0:
                log(f"Within active window ({now.strftime('%H:%M:%S')} WIB). Spawning caffeinate for {remaining_seconds} seconds...")
                try:
                    proc = subprocess.Popen([
                        "/usr/bin/caffeinate",
                        "-dis",
                        "-t",
                        str(remaining_seconds)
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    save_pid(proc.pid)
                    log(f"caffeinate spawned successfully with PID: {proc.pid}")
                except Exception as e:
                    log(f"Failed to spawn caffeinate: {e}")
            else:
                log("Zero seconds remaining in active window, skipping caffeinate spawn.")
    else:
        if caffeinate_active:
            log(f"Outside active window. Terminating caffeinate process (PID: {running_pid})...")
            try:
                os.kill(running_pid, 15) # SIGTERM
                log("caffeinate process terminated.")
            except Exception as e:
                log(f"Error terminating caffeinate: {e}")
            remove_pid_file()

if __name__ == "__main__":
    main()
