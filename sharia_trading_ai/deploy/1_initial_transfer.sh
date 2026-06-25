#!/usr/bin/env bash
# LANGKAH 1 (sekali saja): pindahkan seluruh aplikasi (kode + data) MacBook → Mac mini.
# Lewat Thunderbolt Bridge / LAN (rsync via SSH). TIDAK menyalin .venv (dibuat ulang di Mac mini).
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo "→ Transfer awal ke ${MACMINI}:${APP_DIR}"
echo "  (pastikan 'Remote Login/SSH' aktif di Mac mini: System Settings → General → Sharing → Remote Login)"

# Buat folder tujuan
ssh "${MACMINI}" "mkdir -p '${APP_DIR}'"

rsync -avz --progress \
  --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude '.ocrtmp/' --exclude '.DS_Store' --exclude '*.log' \
  ./ "${MACMINI}:${APP_DIR}/"

echo
echo "✓ Transfer selesai. Lanjut: jalankan 'deploy/2_setup_macmini.sh' (sekali, untuk buat venv di Mac mini)."
