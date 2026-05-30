#!/usr/bin/env bash
# Sharia TA — Telegram Setup Wizard
# ==================================
# Interaktif setup TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID di .env.
# Auto-detect chat_id via getUpdates setelah Anda kirim /start ke bot.
#
# Jalankan: bash ~/Saham/setup_telegram.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
log()  { echo -e "${BLUE}[telegram-setup]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

ENV_FILE="$HOME/Saham/.env"

# --- 1. Verifikasi dependencies ---
if ! command -v curl &>/dev/null; then
    err "curl tidak ditemukan."; exit 1
fi
if ! command -v python3 &>/dev/null; then
    err "python3 tidak ditemukan."; exit 1
fi

# --- 2. Banner & instruksi ---
cat <<'BANNER'

╔════════════════════════════════════════════════════════════════╗
║         Sharia TA — Telegram Setup Wizard                      ║
╚════════════════════════════════════════════════════════════════╝

PRA-SYARAT (lakukan ini di HP/Telegram Anda dulu):

  1. Buka Telegram, cari @BotFather → Start
  2. Ketik: /newbot
  3. Beri nama bot (bebas, mis: "Sharia TA Bot")
  4. Beri username (harus diakhiri "bot", mis: "shariata_hanif_bot")
  5. BotFather kirim BOT TOKEN — copy itu (format: 12345:AAH...)
  6. Cari bot Anda di Telegram, ketik: /start

Jika sudah, paste BOT TOKEN di bawah.

BANNER

# --- 3. Tanyakan token ---
read -rp "BOT TOKEN: " BOT_TOKEN
BOT_TOKEN=$(echo "$BOT_TOKEN" | tr -d '[:space:]')

if [ -z "$BOT_TOKEN" ]; then
    err "Token kosong. Abort."
    exit 1
fi

# Basic format validation: digits:string format
if ! echo "$BOT_TOKEN" | grep -qE '^[0-9]+:[A-Za-z0-9_-]+$'; then
    warn "Token format aneh — biasanya: <digits>:<random_string>. Lanjut tetap?"
    read -rp "Lanjut? [y/N]: " yn
    [[ "$yn" =~ ^[Yy]$ ]] || exit 1
fi

# --- 4. Validate via getMe ---
log "Validating token via Telegram getMe API..."
ME_JSON=$(curl -s --max-time 10 "https://api.telegram.org/bot${BOT_TOKEN}/getMe")
ME_OK=$(echo "$ME_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok',False))")
if [ "$ME_OK" != "True" ]; then
    err "Token invalid. Response:"
    echo "$ME_JSON" | python3 -m json.tool || echo "$ME_JSON"
    exit 1
fi
BOT_USERNAME=$(echo "$ME_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'].get('username',''))")
BOT_NAME=$(echo "$ME_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'].get('first_name',''))")
ok "Token valid! Bot: ${BOT_NAME} (@${BOT_USERNAME})"

# --- 5. Polling getUpdates untuk auto-detect chat_id ---
echo
echo -e "${CYAN}┌────────────────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│  SEKARANG: buka Telegram, cari @${BOT_USERNAME}                   │${NC}"
echo -e "${CYAN}│  Kirim pesan APAPUN ke bot itu (mis: \"halo\", atau /start)  │${NC}"
echo -e "${CYAN}│  Saya akan auto-detect chat_id Anda…                       │${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────────────────┘${NC}"
echo

CHAT_ID=""
ATTEMPTS=0
MAX_ATTEMPTS=30  # 30 × 3s = 90 detik

while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
    sleep 3
    ATTEMPTS=$((ATTEMPTS + 1))
    UPD_JSON=$(curl -s --max-time 10 "https://api.telegram.org/bot${BOT_TOKEN}/getUpdates")
    PARSED=$(echo "$UPD_JSON" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if not d.get('ok') or not d.get('result'):
        sys.exit(0)
    # Get LATEST message
    latest = d['result'][-1]
    msg = latest.get('message') or latest.get('edited_message') or {}
    chat = msg.get('chat', {})
    cid = chat.get('id')
    name = chat.get('first_name') or chat.get('title') or chat.get('username') or '?'
    print(f'{cid}|{name}')
except Exception:
    pass
")
    if [ -n "$PARSED" ]; then
        CHAT_ID="${PARSED%%|*}"
        CHAT_NAME="${PARSED##*|}"
        ok "Detected chat: '$CHAT_NAME' (chat_id=$CHAT_ID)"
        break
    fi
    printf "."
done
echo

if [ -z "$CHAT_ID" ]; then
    err "Tidak ada pesan masuk dalam 90 detik."
    err "Pastikan Anda sudah:"
    err "  1. Search bot @${BOT_USERNAME} di Telegram"
    err "  2. Kirim pesan apapun ke bot (mis. /start)"
    err "Lalu jalankan script ini lagi."
    exit 1
fi

# --- 6. Konfirmasi ---
echo
echo -e "${YELLOW}Akan disimpan ke ${ENV_FILE}:${NC}"
echo "  TELEGRAM_BOT_TOKEN=${BOT_TOKEN:0:10}...${BOT_TOKEN: -4}"
echo "  TELEGRAM_CHAT_ID=${CHAT_ID}"
echo "  TELEGRAM_ENABLED=true"
echo
read -rp "Konfirmasi simpan? [Y/n]: " yn
if [[ "$yn" =~ ^[Nn]$ ]]; then
    warn "Abort. .env tidak diubah."
    exit 0
fi

# --- 7. Backup & update .env ---
if [ ! -f "$ENV_FILE" ]; then
    log "Creating new .env"
    cat > "$ENV_FILE" <<EOF
# Sharia TA — Environment variables
TELEGRAM_BOT_TOKEN=${BOT_TOKEN}
TELEGRAM_CHAT_ID=${CHAT_ID}
TELEGRAM_ENABLED=true
TRADING_MODE=swing
EOF
else
    cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    ok "Backup .env → ${ENV_FILE}.bak.*"
    # Replace 3 keys (idempotent) — use python for safe rewrite
    python3 <<PY
import os, re
path = "$ENV_FILE"
with open(path, "r") as f:
    content = f.read()

def upsert(content, key, value):
    pat = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pat.search(content):
        return pat.sub(f"{key}={value}", content)
    # append if not present
    if not content.endswith("\n"):
        content += "\n"
    return content + f"{key}={value}\n"

content = upsert(content, "TELEGRAM_BOT_TOKEN", "$BOT_TOKEN")
content = upsert(content, "TELEGRAM_CHAT_ID", "$CHAT_ID")
content = upsert(content, "TELEGRAM_ENABLED", "true")
with open(path, "w") as f:
    f.write(content)
print("OK")
PY
fi
ok ".env updated"

# --- 8. Restart app supaya env baru ke-load ---
log "Restart com.shariata.app agar env baru ke-load…"
if launchctl kickstart -k "gui/$(id -u)/com.shariata.app" 2>/dev/null; then
    ok "Launchd app di-restart"
    sleep 5
else
    warn "Gagal restart via launchctl. Restart manual:"
    warn "  launchctl unload ~/Library/LaunchAgents/com.shariata.app.plist"
    warn "  launchctl load   ~/Library/LaunchAgents/com.shariata.app.plist"
fi

# --- 9. Send test message ---
log "Sending test message via /api/telegram/test…"
TEST_JSON=$(curl -s --max-time 15 -X POST http://127.0.0.1:8000/api/telegram/test 2>/dev/null || echo '{}')
TEST_OK=$(echo "$TEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok',False))" 2>/dev/null || echo "False")

echo
echo "=== Test Result ==="
echo "$TEST_JSON" | python3 -m json.tool 2>/dev/null || echo "$TEST_JSON"
echo

if [ "$TEST_OK" = "True" ]; then
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✅ TELEGRAM BERFUNGSI!                                         ${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo
    echo "Buka Telegram → bot @${BOT_USERNAME} — pesan test sudah masuk."
    echo
    echo "Scheduler akan mengirim alert otomatis sesuai jadwal di scheduler.py:"
    echo "  06:00 WIB — rebuild master data"
    echo "  08:45 WIB — Pre-market brief (morning)"
    echo "  09:02 WIB — Morning boost alert (breakout setup)"
    echo "  12:05/11:35 WIB — Mid-day brief sesi I"
    echo "  14:45 WIB — Closing push alert (sore akumulasi)"
    echo "  Per 30 menit (sesuai TRADING_MODE) — intraday alert scan"
    echo
    echo "Test ulang kapan saja:"
    echo "  curl -X POST http://127.0.0.1:8000/api/telegram/test"
    echo "  curl http://127.0.0.1:8000/api/telegram/diagnose | python3 -m json.tool"
else
    echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  ⚠ Test gagal — cek diagnose:                                  ${NC}"
    echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
    echo
    curl -s --max-time 10 http://127.0.0.1:8000/api/telegram/diagnose | python3 -m json.tool 2>/dev/null
fi
