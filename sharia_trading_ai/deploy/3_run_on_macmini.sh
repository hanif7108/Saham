#!/usr/bin/env bash
# LANGKAH 3: jalankan server di Mac mini (bind 0.0.0.0 → bisa diakses dari MacBook).
# Jalankan dari MacBook (via SSH) ATAU langsung di Mac mini.
# Mode latar belakang (tetap jalan walau SSH ditutup) memakai nohup.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

start_remote() {
  ssh "${MACMINI}" bash -lc "'
    cd \"${APP_DIR}\"
    pkill -f \"uvicorn app.main:app\" 2>/dev/null || true
    sleep 1
    nohup env TZ="Asia/Jakarta" ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT} \
      >/tmp/sharia_server.log 2>&1 &
    sleep 2
    echo \"Server jalan di Mac mini: http://0.0.0.0:${APP_PORT} (PID \$(pgrep -f uvicorn | head -1))\"
  '"
  echo
  echo "✓ Akses dari MacBook (browser):  http://${MACMINI_HOST}:${APP_PORT}"
  echo "  Cek alamat Thunderbolt Mac mini:  ssh ${MACMINI} 'ipconfig getifaddr bridge0 2>/dev/null || ipconfig getifaddr en0'"
}

start_remote
