#!/bin/bash
# tv_watchdog.sh — supervisor TradingView untuk Sharia Trading Assistant.
#
# Dijalankan berkala oleh launchd (com.shariata.tvwatchdog):
#   - DALAM jendela koneksi (±60mnt jam bursa, waktu BMKG/WIB): pastikan TradingView
#     HIDUP dengan --remote-debugging-port=9222 (kill+relaunch bila port mati,
#     menangani kasus TradingView jalan tanpa flag).
#   - DI LUAR jendela: TUTUP TradingView → tidak ada interkoneksi sama sekali.
#
# Keputusan jendela memakai modules.market_hours.is_connectivity_window() yang
# merujuk waktu nasional BMKG (modules.time_sync, ntp.bmkg.go.id).

set -u
SAHAM_DIR="/Users/hanif/Saham"
PORT=9222
# 1 = tutup TradingView di luar jendela koneksi (interkoneksi benar-benar berhenti).
# 0 = biarkan TradingView terbuka di luar jendela (poll tetap berhenti, app tak ditutup).
QUIT_OUTSIDE_WINDOW=1
PY="$SAHAM_DIR/venv/bin/python"
LOG="$SAHAM_DIR/logs/tv_watchdog.log"
mkdir -p "$SAHAM_DIR/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

port_up() { curl -s --max-time 3 "http://127.0.0.1:$PORT/json/version" >/dev/null 2>&1; }
tv_running() { pgrep -if "TradingView.app/Contents/MacOS/TradingView" >/dev/null 2>&1; }

# Dalam jendela koneksi? exit 0 = ya, 1 = tidak.
if "$PY" -c "import sys; sys.path.insert(0,'$SAHAM_DIR'); from modules.market_hours import is_connectivity_window; sys.exit(0 if is_connectivity_window() else 1)" 2>>"$LOG"; then
  IN_WINDOW=1
else
  IN_WINDOW=0
fi

if [ "$IN_WINDOW" = "1" ]; then
  if port_up; then
    : # sehat, tidak perlu apa-apa
  else
    log "DALAM jendela & port $PORT mati — relaunch TradingView"
    pkill -9 -i -f "TradingView" 2>/dev/null
    sleep 3
    open -a TradingView --args --remote-debugging-port=$PORT
    sleep 8
    if port_up; then log "TradingView hidup, port $PORT OK"; else log "GAGAL: port $PORT tetap mati"; fi
  fi
else
  if [ "$QUIT_OUTSIDE_WINDOW" = "1" ] && tv_running; then
    log "DI LUAR jendela — tutup TradingView (hentikan interkoneksi)"
    osascript -e 'quit app "TradingView"' 2>/dev/null
    sleep 2
    pkill -9 -i -f "TradingView" 2>/dev/null
  fi
fi
