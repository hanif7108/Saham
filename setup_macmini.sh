#!/usr/bin/env bash
# Sharia Trading Assistant — One-Shot Setup Wrapper
# Dibuat oleh Claude untuk menghindari paste error di zsh.
# Jalankan: bash ~/Saham/setup_macmini.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'
log()  { echo -e "${BLUE}[setup]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

cd "$HOME/Saham"

# --- Step 1: Bersihkan venv Linux yang dibuat sandbox Claude ---
if [ -d "venv_BROKEN_LINUX_DELETE_ME" ]; then
    log "Menghapus venv Linux yang tidak terpakai..."
    rm -rf venv_BROKEN_LINUX_DELETE_ME
    ok "venv_BROKEN_LINUX_DELETE_ME dihapus"
else
    ok "venv_BROKEN_LINUX_DELETE_ME tidak ada (sudah bersih)"
fi

# --- Step 2: Setup venv macOS + install dependencies ---
log "Menjalankan ./run.sh --setup ..."
./run.sh --setup
ok "Setup venv + dependencies selesai"

# --- Step 3: Smoke test app (background, 8 detik, lalu kill) ---
log "Smoke test gunicorn (background, ~10 detik)..."
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
"$HOME/Saham/venv/bin/python3" -m gunicorn -c deploy/gunicorn_config.py app:app > /tmp/saham_smoketest.log 2>&1 &
GPID=$!
sleep 10

echo
echo "=== Smoke test endpoint utama ==="
for ep in /api/portfolio /api/trading_mode /api/cache/stats /api/decisions /api/market /api/dashboard; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:8000${ep}" 2>/dev/null)
    if [ "$code" = "200" ]; then
        ok "${ep}  ->  ${code}"
    else
        warn "${ep}  ->  ${code}"
    fi
done

echo
log "Menghentikan gunicorn smoke test..."
kill $GPID 2>/dev/null || true
pkill -f "gunicorn .* app:app" 2>/dev/null || true
pkill -f "run_scheduler.py" 2>/dev/null || true
sleep 2

# --- Step 4: Register launchd ---
echo
log "Memasang launchd services (app + caffeinate + pipeline)..."
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCHD_DIR"

# Replace /Users/hanif kalau username beda (di sini sama, tapi defensive)
ACTUAL_HOME="$HOME"
for plist in com.shariata.app.plist com.shariata.caffeinate.plist com.shariata.pipeline.plist; do
    sed "s|/Users/hanif|$ACTUAL_HOME|g" "deploy/macmini/$plist" > "$LAUNCHD_DIR/$plist"
    ok "Dipasang: $plist"
done

# Unload kalau sudah ada (idempotent), lalu load fresh
for label in com.shariata.app com.shariata.caffeinate com.shariata.pipeline; do
    launchctl unload "$LAUNCHD_DIR/${label}.plist" 2>/dev/null || true
    launchctl load -w "$LAUNCHD_DIR/${label}.plist"
    ok "Loaded: $label"
done

# --- Step 5: Verifikasi ---
echo
log "Verifikasi services..."
sleep 5

echo
echo "=== launchctl list (filter shariata) ==="
launchctl list | grep shariata || warn "Tidak ada service shariata terdaftar"

echo
echo "=== HTTP endpoint test ==="
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://127.0.0.1:8000/api/cache/stats 2>/dev/null)
if [ "$code" = "200" ]; then
    ok "Gunicorn live di http://127.0.0.1:8000 (response 200)"
else
    warn "Gunicorn belum responsif (code=$code). Cek log:"
    echo "    tail -f ~/Saham/logs/launchd_stderr.log"
fi

echo
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  SETUP SELESAI${NC}"
echo -e "${GREEN}========================================${NC}"
echo
echo "Akses dashboard:  http://127.0.0.1:8000"
echo "Cek IP Mac mini:  ipconfig getifaddr en0   (atau en1)"
echo
echo "Manajemen:"
echo "  Status  : launchctl list | grep shariata"
echo "  Logs    : tail -f ~/Saham/logs/launchd_stderr.log"
echo "  Restart : bash ~/Saham/restart_gunicorn.sh"
echo
echo "Telegram alert masih nonaktif. Untuk aktifkan:"
echo "  1. Edit ~/Saham/.env  →  isi TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED=true"
echo "  2. Restart: launchctl kickstart -k gui/\$(id -u)/com.shariata.app"
echo "  3. Test  : curl -X POST http://127.0.0.1:8000/api/telegram/test"
echo
