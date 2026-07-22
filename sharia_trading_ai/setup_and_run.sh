#!/usr/bin/env bash
# ==============================================================================
# Installer & Runner Portabel untuk Sharia Trading AI (macOS)
# ==============================================================================
set -euo pipefail

echo "========================================================"
echo "   ☪  Sharia Trading AI Portable Installer & Runner (macOS)"
echo "========================================================"

# 1. Cek Python 3
if ! command -v python3 &>/dev/null; then
    echo "❌ Error: Python 3 tidak ditemukan. Harap instal Python 3 terlebih dahulu."
    exit 1
fi

# 2. Cek/Instal virtualenv & dependensi
echo "=> Menyiapkan Virtual Environment Python..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 3. Jalankan Server FastAPI
PORT=8000
echo ""
echo "=> Sharia Trading AI siap dijalankan!"
echo "   Aplikasi akan berjalan di http://localhost:${PORT}"
echo "========================================================"
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
