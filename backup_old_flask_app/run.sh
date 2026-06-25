#!/usr/bin/env bash
# Sharia Trading Assistant — Quick Start (macOS / Linux)
# Usage:
#   ./run.sh            # start app (default port 5000)
#   ./run.sh --port 8000
#   ./run.sh --rebuild  # rebuild master data dulu sebelum start
#   ./run.sh --setup    # install deps saja, jangan start app

set -e

cd "$(dirname "$0")"
SAHAM_DIR="$(pwd)"

# ---------- Color helpers ----------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'
log() { echo -e "${BLUE}[run.sh]${NC} $*"; }
ok()  { echo -e "${GREEN}✓${NC} $*"; }
warn(){ echo -e "${YELLOW}!${NC} $*"; }
err() { echo -e "${RED}✗${NC} $*" >&2; }

# ---------- Parse args ----------
# Default port 8000 untuk hindari konflik dengan macOS AirPlay Receiver (port 5000)
PORT=8000
DO_REBUILD=0
DO_SETUP_ONLY=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --port) PORT="$2"; shift 2;;
        --rebuild) DO_REBUILD=1; shift;;
        --setup) DO_SETUP_ONLY=1; shift;;
        *) err "Argumen tidak dikenal: $1"; exit 1;;
    esac
done

# ---------- 1. Cek Python ----------
log "Mengecek Python..."
if ! command -v python3 &> /dev/null; then
    err "python3 tidak ditemukan."
    err "Install dari https://www.python.org/downloads/ atau via Homebrew: brew install python@3.11"
    exit 1
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
    err "Butuh Python 3.9+, ditemukan $PY_VER"
    exit 1
fi
ok "Python $PY_VER ditemukan"

# ---------- 2. Setup venv ----------
VENV_DIR="$SAHAM_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    log "Membuat virtualenv di venv/ ..."
    python3 -m venv "$VENV_DIR"
    ok "Virtualenv dibuat"
else
    ok "Virtualenv sudah ada"
fi

# Activate
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ---------- 3. Install deps ----------
log "Mengecek dependencies..."
NEEDS_INSTALL=0
for pkg in flask pandas yfinance apscheduler openpyxl reportlab requests; do
    if ! python -c "import $pkg" 2>/dev/null; then
        NEEDS_INSTALL=1
        break
    fi
done

if [ $NEEDS_INSTALL -eq 1 ]; then
    log "Install dependencies (sekali saja, ~1-2 menit)..."
    pip install --upgrade pip > /dev/null
    pip install -r deploy/requirements.txt
    ok "Dependencies terinstall"
else
    ok "Semua dependencies sudah ada"
fi

# ---------- 4. Verifikasi files ----------
log "Mengecek file data..."
if [ ! -f "daftar_saham_syariah.csv" ]; then
    err "daftar_saham_syariah.csv tidak ditemukan"
    exit 1
fi
N_TICKERS=$(($(wc -l < daftar_saham_syariah.csv) - 1))
ok "Daftar saham syariah: $N_TICKERS ticker"

if [ ! -f "master_data_syariah.csv" ] || [ "$DO_REBUILD" -eq 1 ]; then
    if [ "$DO_REBUILD" -eq 1 ]; then
        warn "Rebuild master data diminta — akan memakan waktu ~3 menit..."
    else
        warn "master_data_syariah.csv belum ada — akan generate otomatis (~3 menit)..."
    fi
    python build_master_data.py
    ok "Master data siap"
else
    N_MASTER=$(($(wc -l < master_data_syariah.csv) - 1))
    ok "Master data siap: $N_MASTER ticker"
fi

# Buat folder kalau belum ada
mkdir -p cache logs exports

# ---------- 5. Setup only? ----------
if [ "$DO_SETUP_ONLY" -eq 1 ]; then
    ok "Setup selesai. Untuk start: ./run.sh"
    exit 0
fi

# ---------- 6. Start app ----------
echo
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Sharia Trading Assistant — RUNNING${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "  URL:   ${BLUE}http://127.0.0.1:$PORT${NC}"
echo -e "  Stop:  Ctrl+C"
echo

# Override port via env var (Flask debug auto-restart akan baca ini)
export FLASK_RUN_PORT=$PORT

# Open browser otomatis (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    (sleep 2 && open "http://127.0.0.1:$PORT") &
fi

# Start
python app.py
