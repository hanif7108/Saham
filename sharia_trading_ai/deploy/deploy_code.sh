#!/usr/bin/env bash
# UPDATE KODE (rutin): kirim perubahan kode MacBook → Mac mini TANPA menyentuh data_store.
# Pakai ini tiap kali Anda mengubah program di MacBook lalu ingin Mac mini ikut terbarui.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo "→ Deploy KODE ke ${MACMINI} (data_store TIDAK diubah)"
rsync -avz --delete \
  --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude '.ocrtmp/' --exclude '.DS_Store' --exclude '*.log' \
  --exclude 'data_store/' --exclude 'data_cache/' \
  ./ "${MACMINI}:${APP_DIR}/"

echo "→ Update dependensi & restart server di Mac mini"
ssh -t "${MACMINI}" "
  cd '${APP_DIR}'
  ./.venv/bin/pip install -q -r requirements.txt
  if [ -f /Library/LaunchDaemons/com.sharia.trading.plist ]; then
    sudo launchctl kickstart -k system/com.sharia.trading && echo 'restart via launchd (auto-start)'
  else
    pkill -f 'uvicorn app.main' 2>/dev/null || true; sleep 1
    nohup env TZ="Asia/Jakarta" ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT} >/tmp/sharia_server.log 2>&1 &
    echo 'restart via nohup'
  fi
  sleep 2; lsof -nP -iTCP:${APP_PORT} -sTCP:LISTEN || echo '(cek log /tmp/sharia_server.log)'
"
echo "✓ Kode terbarui & server di-restart. Data trading utuh."
