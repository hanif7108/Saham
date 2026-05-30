#!/usr/bin/env bash
# Apply patch dari PERBAIKAN_SAHAM.md ke instance launchd Mac mini.
#
# Patch sudah ditulis ke file (modules/market_hours.py [BARU], modules/cache.py,
# modules/scheduler.py, app.py, deploy/gunicorn_config.py). Script ini cuma:
#   1. Pre-flight: verifikasi syntax semua file Python yang dipatch
#   2. Restart launchd agent agar gunicorn pakai kode baru
#   3. Verifikasi endpoint /api/health + /api/market_status return 200
#
# Jalankan: bash ~/Saham/apply_patch.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'
log()  { echo -e "${BLUE}[patch]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

cd "$HOME/Saham"

# --- 1. Pre-flight syntax check ---
log "Pre-flight syntax check..."
VENV_PY="$HOME/Saham/venv/bin/python3"
if [ ! -x "$VENV_PY" ]; then
    err "venv belum ada. Jalankan dulu: ./run.sh --setup"
    exit 1
fi

for f in modules/market_hours.py modules/cache.py modules/scheduler.py modules/aaoifi.py modules/rebalancer.py app.py deploy/gunicorn_config.py build_master_us.py; do
    if "$VENV_PY" -m py_compile "$f"; then
        ok "syntax OK: $f"
    else
        err "syntax error: $f — STOP, fix dulu"
        exit 1
    fi
done

# --- 2. Verifikasi import smoke (app + scheduler attach) ---
log "Verify app.py import-able dengan scheduler auto-start..."
"$VENV_PY" - <<'PY'
import sys, os
os.chdir(os.path.expanduser("~/Saham"))
sys.path.insert(0, os.getcwd())
import app
print(f"  version          : {app.APP_VERSION}")
print(f"  routes total     : {len(list(app.app.url_map.iter_rules()))}")
print(f"  has /api/health  : {any(str(r) == '/api/health' for r in app.app.url_map.iter_rules())}")
print(f"  has /api/market_status: {any(str(r) == '/api/market_status' for r in app.app.url_map.iter_rules())}")
print(f"  scheduler_started: {app._SCHEDULER_STATE['started']}")
print(f"  scheduler_error  : {app._SCHEDULER_STATE['error']}")
PY
ok "import smoke pass"

# --- 3. Restart launchd agent ---
log "Restart com.shariata.app launchd agent..."
launchctl kickstart -k "gui/$(id -u)/com.shariata.app" || {
    err "launchctl kickstart gagal. Coba load ulang manual:"
    err "  launchctl unload ~/Library/LaunchAgents/com.shariata.app.plist"
    err "  launchctl load   ~/Library/LaunchAgents/com.shariata.app.plist"
    exit 1
}
ok "App agent restarted"

# Tunggu gunicorn ready
sleep 8

# --- 4. Verifikasi endpoint baru ---
log "Verifikasi endpoint baru..."
echo
echo "=== /api/health ==="
HEALTH_CODE=$(curl -s -o /tmp/saham_health.json -w "%{http_code}" --max-time 10 http://127.0.0.1:8000/api/health)
echo "HTTP code: $HEALTH_CODE"
cat /tmp/saham_health.json | python3 -m json.tool 2>/dev/null || cat /tmp/saham_health.json
echo
echo "=== /api/market_status ==="
MARKET_CODE=$(curl -s -o /tmp/saham_market.json -w "%{http_code}" --max-time 10 http://127.0.0.1:8000/api/market_status)
echo "HTTP code: $MARKET_CODE"
cat /tmp/saham_market.json | python3 -m json.tool 2>/dev/null || cat /tmp/saham_market.json
echo

if [ "$HEALTH_CODE" = "200" ] && [ "$MARKET_CODE" = "200" ]; then
    SCHED_OK=$(python3 -c "import json; d=json.load(open('/tmp/saham_health.json')); print(d.get('scheduler_started'))")

    # Cek juga endpoint US (5 endpoint baru)
    echo
    echo "=== US Stock endpoints ==="
    US_PASS=0
    for ep in /api/us/market_status /api/us/universe /api/us/master /api/us/top5 /api/us/portfolio; do
        c=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:8000${ep}")
        echo "  ${ep} -> ${c}"
        [ "$c" = "200" ] && US_PASS=$((US_PASS+1))
    done
    echo "US endpoint pass: $US_PASS / 5"
    echo
    echo "=== /api/us/market_status ==="
    curl -s --max-time 8 http://127.0.0.1:8000/api/us/market_status | python3 -m json.tool 2>/dev/null

    if [ "$SCHED_OK" = "True" ] && [ "$US_PASS" = "5" ]; then
        echo
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}  PATCH APPLIED SUCCESSFULLY${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo
        echo "Yang berubah:"
        echo "  ✓ modules/market_hours.py — kalender libur IDX + NYSE/NASDAQ + sesi"
        echo "  ✓ modules/cache.py — TTL adaptif + multi-market routing (.JK auto)"
        echo "  ✓ modules/scheduler.py — gating hari libur + sys.executable + log mirror"
        echo "  ✓ modules/aaoifi.py [BARU] — Shariah screening US stocks"
        echo "  ✓ modules/rebalancer.py — 4-bucket alloc (IDX/US/Emas/Cash)"
        echo "  ✓ app.py — endpoint /api/health, /api/market_status, /api/us/* (10 baru),"
        echo "             portfolio lock + atomic write, scheduler auto-start"
        echo "  ✓ deploy/gunicorn_config.py — preload_app=False, workers default 1"
        echo "  ✓ build_master_us.py [BARU] — builder data fundamental US"
        echo "  ✓ daftar_saham_syariah_us.csv [BARU] — universe 50 ticker HLAL-style"
        echo "  ✓ templates/index.html — 2 tab baru (IDX Stock, US Stock), Dashboard simplified"
        echo "  ✓ static/app.js — handler loadIDXStockTab, loadUSStockTab, chart IHSG/NDX"
        echo
        echo "Langkah selanjutnya:"
        echo "  1. Build master data US (sekali saja, ~2 menit untuk 50 ticker):"
        echo "       ~/Saham/venv/bin/python3 ~/Saham/build_master_us.py"
        echo "     atau klik tombol '🔄 Build Master' di tab US Stock."
        echo
        echo "  2. Buka browser ke http://127.0.0.1:8000 → klik tab '🇺🇸 US Stock'"
        echo
        echo "Cek versi & status:"
        echo "  curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool"
        echo "  curl -s http://127.0.0.1:8000/api/us/market_status | python3 -m json.tool"
        echo
        echo "Log:"
        echo "  tail -f ~/Saham/logs/scheduler.log"
        echo "  tail -f ~/Saham/logs/gunicorn_error.log"
    else
        warn "Scheduler NOT started: $SCHED_OK — cek logs/gunicorn_error.log"
    fi
else
    err "Endpoint check FAILED. /api/health=$HEALTH_CODE, /api/market_status=$MARKET_CODE"
    err "Tail log: tail -50 ~/Saham/logs/launchd_stderr.log"
    exit 1
fi
