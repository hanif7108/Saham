#!/usr/bin/env bash
# Diagnosa "ERR_CONNECTION_REFUSED". Jalankan dari MacBook: ./deploy/diagnose.sh
set -uo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo "=== 1) Resolusi nama & jangkauan ${MACMINI_HOST} ==="
if ping -c1 -t2 "${MACMINI_HOST}" >/dev/null 2>&1; then
  echo "  ✓ ${MACMINI_HOST} terjangkau"
else
  echo "  ✗ TIDAK terjangkau → cek kabel Thunderbolt, 'Thunderbolt Bridge' di Network kedua Mac, & Remote Login (SSH) di Mac mini."
  exit 1
fi

echo "=== 2) Status di Mac mini (via SSH) ==="
ssh -o ConnectTimeout=5 "${MACMINI}" bash -lc "'
  echo \"  • listener port ${APP_PORT}:\"
  lsof -nP -iTCP:${APP_PORT} -sTCP:LISTEN 2>/dev/null | sed \"s/^/      /\" || echo \"      (KOSONG — server belum jalan / tidak listen)\"
  echo \"  • proses uvicorn:\"; pgrep -fl uvicorn | sed \"s/^/      /\" || echo \"      (tidak ada)\"
  echo \"  • venv uvicorn:\"; (ls ${APP_DIR}/.venv/bin/uvicorn >/dev/null 2>&1 && echo \"      ada\") || echo \"      (.venv BELUM dibuat → jalankan deploy/2_setup_macmini.sh)\"
  echo \"  • tes lokal /health di Mac mini:\"; (curl -s -m3 http://127.0.0.1:${APP_PORT}/health && echo) | sed \"s/^/      /\" || echo \"      (gagal — server tidak jalan)\"
  echo \"  • 5 baris log terakhir:\"; tail -5 /tmp/sharia_server.log 2>/dev/null | sed \"s/^/      /\" || echo \"      (tak ada log)\"
'"

echo "=== 3) Tes akses dari MacBook → Mac mini ==="
if curl -s -m4 "http://${MACMINI_HOST}:${APP_PORT}/health" >/dev/null 2>&1; then
  echo "  ✓ BISA diakses: http://${MACMINI_HOST}:${APP_PORT}"
else
  echo "  ✗ refused/timeout. Lihat hasil bagian 2:"
  echo "     - listener KOSONG / tak ada uvicorn  → server belum jalan:  ./deploy/3_run_on_macmini.sh"
  echo "     - listener tertulis 127.0.0.1:${APP_PORT} → terikat localhost → restart bind 0.0.0.0:  ./deploy/3_run_on_macmini.sh"
  echo "     - .venv belum ada                    → ./deploy/2_setup_macmini.sh dulu"
  echo "     - lokal /health OK tapi sini gagal   → Firewall Mac mini blokir: System Settings → Network → Firewall → Options → izinkan python/uvicorn (atau OFF utk uji)"
fi
