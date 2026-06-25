#!/usr/bin/env bash
# Sharia Trading Assistant — Mac Mini 24/7 Installer
# ===================================================
# Usage:
#   chmod +x deploy/macmini/install_macmini.sh
#   ./deploy/macmini/install_macmini.sh
#
# Apa yang dilakukan:
#   1. Buat venv + install dependencies
#   2. Copy launchd plist ke ~/Library/LaunchAgents/
#   3. Load services (app + caffeinate)
#   4. Setup pmset untuk power management
#   5. Setup logrotate (newsyslog)
#   6. Verify

set -e
cd "$(dirname "$0")/../.."  # ke root Saham/
SAHAM_DIR="$(pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'
log()  { echo -e "${BLUE}[install]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

if [[ "$OSTYPE" != "darwin"* ]]; then
    err "Script ini KHUSUS macOS. OS Anda: $OSTYPE"
    exit 1
fi

# ---------- 1. Pastikan Python & venv ----------
log "Setup Python venv..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    ok "venv dibuat"
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r deploy/requirements.txt
ok "Dependencies terinstall (termasuk gunicorn)"

# ---------- 2. Pastikan folder & file siap ----------
mkdir -p logs cache exports
[ -f portfolio.csv ] || echo "Ticker,Harga Beli,Jumlah Lot" > portfolio.csv
[ -f master_data_syariah.csv ] || warn "master_data_syariah.csv belum ada — jalankan: python3 build_master_data.py"

# ---------- 3. Setup .env kalau belum ----------
if [ ! -f ".env" ]; then
    cat > .env <<EOF
# Sharia TA — Environment variables
# Isi dengan kredensial Telegram Anda. Lihat panduan di modules/telegram_notify.py

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Optional — SMTP untuk email alert (kalau tidak pakai Telegram)
# SMTP_HOST=smtp.gmail.com
# SMTP_USER=your@gmail.com
# SMTP_PASS=your-app-password
# ALERT_TO=hanif0208@gmail.com

# Mode trading: swing | scalping
# swing    = Taichi default (CL -3% / TP +6%)
# scalping = (CL -1% / TP +2%, scan tiap 5 menit selama jam pasar)
TRADING_MODE=swing
EOF
    warn "File .env dibuat — EDIT dengan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID Anda!"
else
    ok ".env sudah ada (tidak di-overwrite)"
fi

# ---------- 4. Generate launchd plist dengan path absolut ----------
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCHD_DIR"

# Replace placeholder /Users/hanif dengan $HOME aktual (untuk kasus username beda)
ACTUAL_HOME="$HOME"
sed "s|/Users/hanif|$ACTUAL_HOME|g" deploy/macmini/com.shariata.app.plist \
    > "$LAUNCHD_DIR/com.shariata.app.plist"
sed "s|/Users/hanif|$ACTUAL_HOME|g" deploy/macmini/com.shariata.caffeinate.plist \
    > "$LAUNCHD_DIR/com.shariata.caffeinate.plist"
ok "launchd plist dipasang di $LAUNCHD_DIR/"

# ---------- 5. Load services ----------
log "Memuat services ke launchd..."

# Unload kalau sudah ada (idempotent)
launchctl unload "$LAUNCHD_DIR/com.shariata.app.plist" 2>/dev/null || true
launchctl unload "$LAUNCHD_DIR/com.shariata.caffeinate.plist" 2>/dev/null || true

launchctl load -w "$LAUNCHD_DIR/com.shariata.caffeinate.plist"
ok "caffeinate service loaded (cegah sleep)"

launchctl load -w "$LAUNCHD_DIR/com.shariata.app.plist"
ok "Sharia TA app service loaded"

# ---------- 6. Power management (pmset) ----------
log "Mengatur power management..."
# Mac Mini sebaiknya: never sleep, displaysleep ok, restart on power failure
sudo pmset -a sleep 0 2>/dev/null && ok "System sleep: disabled" || warn "Butuh sudo untuk pmset (skip)"
sudo pmset -a disksleep 0 2>/dev/null || true
sudo pmset -a autorestart 1 2>/dev/null || true   # auto-restart on power failure
sudo pmset -a womp 1 2>/dev/null || true          # wake on network access

# ---------- 7. Setup log rotation ----------
log "Setup log rotation..."
# Sederhana: pakai logrotate via cron, atau hand-built rotation di scheduler
# Kita pakai pendekatan sederhana: weekly rotate via launchd
cat > "$LAUNCHD_DIR/com.shariata.logrotate.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.shariata.logrotate</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>cd $SAHAM_DIR/logs && for f in *.log; do [ -f "\$f" ] && [ \$(stat -f%z "\$f") -gt 10485760 ] && mv "\$f" "\$f.\$(date +%Y%m%d)" && touch "\$f"; done; find . -name "*.log.*" -mtime +30 -delete</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>3</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
</dict>
</plist>
EOF
launchctl unload "$LAUNCHD_DIR/com.shariata.logrotate.plist" 2>/dev/null || true
launchctl load -w "$LAUNCHD_DIR/com.shariata.logrotate.plist"
ok "Log rotation: file >10MB di-rotate, file >30 hari dihapus (jam 03:00)"

# ---------- 8. Verifikasi ----------
echo
log "Verifikasi services..."
sleep 3
if launchctl list | grep -q "com.shariata.app"; then
    ok "App service: RUNNING"
else
    err "App service: NOT RUNNING"
fi
if launchctl list | grep -q "com.shariata.caffeinate"; then
    ok "Caffeinate: RUNNING"
fi

# Test HTTP endpoint
if curl -s --max-time 5 http://127.0.0.1:8000/api/cache/stats > /dev/null; then
    ok "HTTP endpoint responding di port 8000"
else
    warn "HTTP endpoint belum responsif — cek log: tail -f logs/launchd_stderr.log"
fi

echo
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  INSTALASI SELESAI${NC}"
echo -e "${GREEN}========================================${NC}"
echo
echo "Akses: http://127.0.0.1:8000"
echo
echo "Step lanjutan:"
echo "  1. EDIT $SAHAM_DIR/.env dengan TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID Anda"
echo "  2. Restart service: launchctl kickstart -k gui/\$(id -u)/com.shariata.app"
echo "  3. Test Telegram: curl -X POST http://127.0.0.1:8000/api/telegram/test"
echo
echo "Manajemen service:"
echo "  Stop  : launchctl unload ~/Library/LaunchAgents/com.shariata.app.plist"
echo "  Start : launchctl load ~/Library/LaunchAgents/com.shariata.app.plist"
echo "  Logs  : tail -f $SAHAM_DIR/logs/launchd_stderr.log"
echo "  Status: launchctl list | grep shariata"
echo
