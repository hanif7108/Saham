#!/usr/bin/env bash
# LANGKAH 2 (sekali): siapkan venv + install di Mac mini.
# Otomatis memilih Python 3.11+ (aplikasi butuh ≥3.10). Output via stdin-pipe (bebas masalah kutip).
set -uo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

echo "→ Menyiapkan venv & dependensi di ${MACMINI}:${APP_DIR}"
echo "  (install pertama kali bisa 2–5 menit)"

ssh "${MACMINI}" 'bash -s' <<REMOTE
set -e
cd "${APP_DIR}"
PY=""
for c in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 python3.13 python3.12 python3.11; do command -v "\$c" >/dev/null 2>&1 && { PY="\$c"; break; }; done
if [ -z "\$PY" ]; then
  echo ">>> Tak ada Python 3.11+. Pasang dulu:  brew install python@3.12  (atau pasang Homebrew lebih dulu)"
  exit 1
fi
echo "Pakai \$PY (\$(\$PY --version 2>&1))"
rm -rf .venv
"\$PY" -m venv .venv
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt 2>&1 | tail -8
./.venv/bin/python -c "import app.main; print('IMPORT OK')"
echo "Tesseract (OCR): \$(command -v tesseract || echo 'BELUM ADA → brew install tesseract')"
echo "venv siap."
REMOTE

echo "✓ Setup selesai. Jalankan: deploy/3_run_on_macmini.sh  (atau pasang auto-start: deploy/install_autostart.sh)"
