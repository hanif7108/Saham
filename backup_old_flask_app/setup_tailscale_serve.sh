#!/usr/bin/env bash
# Setup Tailscale Serve untuk Sharia Trading Assistant
# ====================================================
# Expose app ke Tailnet via HTTPS dengan domain magic dari Tailscale
# (https://<machine>.<tailnet>.ts.net). Hanya device di Tailnet Anda yang
# bisa akses — internet publik TIDAK bisa.
#
# Cara kerja:
#   Browser di laptop/HP (Tailnet member)
#       │  https://hanifs-mac-mini.<tailnet>.ts.net
#       ▼
#   Tailscale daemon di Mac mini (handle TLS, validasi Tailnet auth)
#       │  http://127.0.0.1:8000
#       ▼
#   gunicorn (sharia-ta app)
#
# Aplikasi tidak perlu diubah — tetap bind ke 127.0.0.1:8000.
# Tailscale yang terminate TLS dan forward ke localhost.
#
# Jalankan: bash ~/Saham/setup_tailscale_serve.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'
log()  { echo -e "${BLUE}[ts-serve]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

# --- 1. Verifikasi Tailscale terinstall ---
if ! command -v tailscale &>/dev/null; then
    err "tailscale CLI tidak ditemukan."
    err "Install via Homebrew (recommended untuk full CLI features):"
    err "    brew install tailscale"
    err "Atau download GUI dari: https://tailscale.com/download/macos"
    exit 1
fi
TS_PATH=$(command -v tailscale)
ok "Tailscale CLI ditemukan di: $TS_PATH"
echo "  $(tailscale version 2>/dev/null | head -1 || echo 'version check gagal')"

# --- 1b. Cek apakah ini App Store version (yang punya bundleIdentifier bug) ---
# CLI App Store ada di /Applications/Tailscale.app/Contents/MacOS/Tailscale
# atau symlink-nya. Subcommand seperti `serve`, `funnel`, `cert` umumnya gagal
# dengan error "BundleIdentifiers.swift:47: Fatal error" karena restriksi
# sandboxing macOS.
APP_STORE_PATH="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
if [ "$TS_PATH" = "$APP_STORE_PATH" ] || [[ "$TS_PATH" == *"/Tailscale.app/"* ]]; then
    err "Anda pakai versi App Store dari Tailscale CLI."
    err "Subcommand 'serve' tidak akan jalan dari Terminal karena sandboxing."
    err ""
    err "FIX: install CLI standalone via Homebrew (boleh coexist dengan GUI App Store):"
    err "    brew install tailscale"
    err ""
    err "Setelah install, JALANKAN ULANG script ini."
    err "Cek path baru: which tailscale  (harus /opt/homebrew/bin atau /usr/local/bin)"
    exit 1
fi
# Quick canary test — kalau bundleIdentifier error muncul, abort.
if tailscale serve status 2>&1 | grep -q "BundleIdentifiers"; then
    err "Detected 'BundleIdentifiers' error — App Store sandboxing issue."
    err "Install CLI standalone: brew install tailscale"
    exit 1
fi
ok "CLI bisa menjalankan subcommand 'serve' (bukan App Store version)"

# --- 2. Cek login status ---
if ! tailscale status --json >/dev/null 2>&1; then
    err "Tailscale belum login atau daemon tidak jalan."
    err "Jalankan: tailscale up"
    exit 1
fi
ok "Tailscale daemon aktif"

# --- 3. Info machine & tailnet ---
log "Info Tailnet:"
SELF_IP=$(tailscale ip -4 2>/dev/null | head -1)
SELF_NAME=$(tailscale status --self --json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d['Self']['DNSName'].rstrip('.'))
except Exception:
    print('')
" 2>/dev/null)

echo "  IP        : ${SELF_IP:-?}"
echo "  Hostname  : ${SELF_NAME:-?}"

if [ -z "$SELF_NAME" ]; then
    warn "Tidak dapat baca DNS name. Tailscale mungkin pakai versi lama."
    warn "Cek manual: tailscale status"
fi

# --- 4. Verifikasi MagicDNS aktif (perlu untuk *.ts.net domain) ---
MAGIC_DNS=$(tailscale status --json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('MagicDNSSuffix', ''))
except Exception:
    print('')
" 2>/dev/null)
if [ -z "$MAGIC_DNS" ]; then
    warn "MagicDNS tidak aktif — *.ts.net URL mungkin tidak resolve."
    warn "Aktifkan di Tailscale admin console → DNS → MagicDNS"
fi
ok "Tailnet suffix: ${MAGIC_DNS:-?}"

# --- 5. HTTPS certs (Let's Encrypt internal Tailscale) ---
log "Memastikan HTTPS certs tersedia (perlu fitur 'HTTPS' diaktifkan di admin console)..."
if ! tailscale cert --help &>/dev/null; then
    warn "Subcommand 'tailscale cert' tidak ada. Update Tailscale ke versi terbaru."
fi

# --- 6. Verifikasi app jalan di 127.0.0.1:8000 ---
log "Memastikan app jalan di 127.0.0.1:8000..."
if ! curl -s --max-time 5 http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
    err "App TIDAK responsif di http://127.0.0.1:8000"
    err "Pastikan launchd agent jalan: launchctl list | grep shariata"
    err "Atau start manual: ./run.sh"
    exit 1
fi
ok "App responsif di http://127.0.0.1:8000"

# --- 7. Configure tailscale serve ---
# Forward HTTPS port 443 dari Tailscale ke http://127.0.0.1:8000.
# Hasil URL: https://<machine>.<tailnet>.ts.net (port 443 default)
log "Mengaktifkan Tailscale Serve (HTTPS 443 → app:8000)..."

# Reset any previous config dulu (idempotent). Port 443 butuh sudo di macOS.
log "Reset previous serve config (kalau ada)..."
sudo tailscale serve reset 2>/dev/null || tailscale serve reset 2>/dev/null || true

# Set serve config — coba syntax baru dulu, fallback ke lama.
# Port 443 = privileged, butuh sudo.
log "Configuring serve dengan sudo (port 443 = privileged)..."
SERVE_OK=0
if sudo tailscale serve --bg --https 443 http://127.0.0.1:8000 2>/tmp/ts_err; then
    ok "tailscale serve configured (syntax baru, sudo)"
    SERVE_OK=1
elif sudo tailscale serve https:443 / http://127.0.0.1:8000 2>>/tmp/ts_err; then
    ok "tailscale serve configured (syntax legacy, sudo)"
    SERVE_OK=1
elif tailscale serve --bg --https 443 http://127.0.0.1:8000 2>>/tmp/ts_err; then
    ok "tailscale serve configured (syntax baru, no sudo — Tailscale ops mode mungkin user)"
    SERVE_OK=1
fi
if [ "$SERVE_OK" -eq 0 ]; then
    err "Gagal configure tailscale serve."
    err "Output error:"
    sed 's/^/    /' /tmp/ts_err
    err ""
    err "Coba manual:"
    err "    sudo tailscale serve --https 443 http://127.0.0.1:8000"
    err "    tailscale serve status"
    exit 1
fi

# --- 8. Verifikasi ---
sleep 3
log "Status tailscale serve:"
tailscale serve status 2>&1 || warn "Tidak bisa baca status"

echo
if [ -n "$SELF_NAME" ]; then
    URL="https://${SELF_NAME}"
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  TAILSCALE SERVE ACTIVE${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo
    echo "Akses Sharia TA dari device manapun di Tailnet Anda:"
    echo
    echo -e "  ${BLUE}${URL}${NC}"
    echo
    echo "Atau via IP Tailscale (no TLS):"
    echo "  http://${SELF_IP}:8000   (Anda harus tetap pastikan iptables Mac mini"
    echo "                            tidak block port 8000 dari Tailnet interface)"
    echo
    echo "Verifikasi dari device Tailnet lain (HP/laptop):"
    echo "  - Install Tailscale di device tersebut, login ke akun yang sama"
    echo "  - Buka browser ke ${URL}"
    echo
else
    echo "Akses URL akan menampilkan magic DNS Tailnet Anda."
    echo "Lihat di admin console Tailscale → Machines → klik mesin ini → DNS Name"
fi

echo "Cara menghentikan Serve (kembali ke localhost-only):"
echo "  tailscale serve reset"
echo
echo "Status:"
echo "  tailscale serve status"
echo
warn "PENTING: jangan jalankan 'tailscale funnel' kecuali Anda mau expose ke"
warn "internet publik (siapapun di dunia bisa akses). Untuk privat (hanya"
warn "device Anda), 'tailscale serve' SUDAH cukup."
