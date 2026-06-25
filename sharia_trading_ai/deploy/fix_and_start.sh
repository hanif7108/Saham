#!/usr/bin/env bash
# Perbaiki & jalankan server di Mac mini dalam SATU langkah, dengan output error lengkap.
# Skrip dikirim ke Mac mini via stdin (bebas masalah kutip). Jalankan dari MacBook.
set -uo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo "→ Menyiapkan & menjalankan di ${MACMINI} (folder ${APP_DIR}, port ${APP_PORT})"
echo "  (pip install pertama kali bisa beberapa menit; tunggu...)"
echo "=================================================================="

ssh "${MACMINI}" 'bash -s' <<REMOTE
set +e
cd "${APP_DIR}" || { echo "GAGAL: folder ${APP_DIR} tidak ada di Mac mini"; exit 1; }

echo "== Python =="
python3 --version 2>&1 || echo "TIDAK ADA python3 (pasang Xcode CLT: xcode-select --install)"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "== Membuat venv & install dependensi (sekali) =="
  python3 -m venv .venv 2>&1
  ./.venv/bin/pip install --upgrade pip >/dev/null 2>&1
  ./.venv/bin/pip install -r requirements.txt 2>&1 | tail -25
fi

echo "== Uji import aplikasi =="
./.venv/bin/python -c "import app.main; print('IMPORT OK')" 2>&1 | tail -25

echo "== Menjalankan server (0.0.0.0:${APP_PORT}) =="
pkill -f "uvicorn app.main" 2>/dev/null; sleep 1
nohup ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT} >/tmp/sharia_server.log 2>&1 &
sleep 5

echo "== Listener =="
lsof -nP -iTCP:${APP_PORT} -sTCP:LISTEN 2>/dev/null || echo "TIDAK ADA LISTENER (server gagal start — lihat log di bawah)"
echo "== Health lokal =="
curl -s -m4 http://127.0.0.1:${APP_PORT}/health || echo "HEALTH GAGAL"
echo
echo "== Log (15 baris terakhir) =="
tail -15 /tmp/sharia_server.log 2>/dev/null
REMOTE

echo "=================================================================="
echo "→ Bila 'IMPORT OK' + listener '*:${APP_PORT}' + health ok →"
echo "  buka di MacBook: http://${MACMINI_HOST}:${APP_PORT}"
echo "  Jika dari MacBook masih refused padahal health lokal OK → Firewall Mac mini (izinkan/OFF)."
