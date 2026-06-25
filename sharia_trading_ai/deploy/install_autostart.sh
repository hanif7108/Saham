#!/usr/bin/env bash
# Pasang AUTO-START di Mac mini (LaunchDaemon): server nyala otomatis tiap boot
# & otomatis restart bila crash — tanpa perlu login/SSH. Perlu password sudo Mac mini.
set -uo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

LABEL="com.sharia.trading"
PLIST_PATH="/Library/LaunchDaemons/${LABEL}.plist"

echo "→ Cek venv di Mac mini..."
if ! ssh "${MACMINI}" "test -x '${APP_DIR}/.venv/bin/uvicorn'"; then
  echo "✗ .venv belum siap di Mac mini. Jalankan dulu: ./deploy/2_setup_macmini.sh"
  exit 1
fi

# PATH menyertakan /opt/homebrew/bin agar Tesseract (OCR) ditemukan oleh launchd.
# Port di bawah 1024 (seperti 80) memerlukan hak akses root, sehingga UserName dikosongkan.
USER_ELEMENT=""
if [ "${APP_PORT}" -ge 1024 ]; then
  USER_ELEMENT="  <key>UserName</key><string>${MACMINI_USER}</string>"
fi

PLIST=$(cat <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
${USER_ELEMENT}
  <key>WorkingDirectory</key><string>${APP_DIR}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${APP_DIR}/.venv/bin/uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string><string>0.0.0.0</string>
    <string>--port</string><string>${APP_PORT}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/sharia_server.log</string>
  <key>StandardErrorPath</key><string>/tmp/sharia_server.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>TZ</key><string>Asia/Jakarta</string>
  </dict>
</dict>
</plist>
PL
)

echo "→ Tulis plist ke /tmp Mac mini (tanpa sudo)..."
printf '%s\n' "${PLIST}" | ssh "${MACMINI}" "cat > /tmp/${LABEL}.plist"

echo "→ Hentikan server manual (jika ada) lalu pasang LaunchDaemon (minta password sudo)..."
ssh -t "${MACMINI}" "
  pkill -f 'uvicorn app.main' 2>/dev/null || true
  sudo mv /tmp/${LABEL}.plist '${PLIST_PATH}'
  sudo chown root:wheel '${PLIST_PATH}'
  sudo chmod 644 '${PLIST_PATH}'
  sudo launchctl bootout system/${LABEL} 2>/dev/null || true
  sudo launchctl bootstrap system '${PLIST_PATH}'
  sleep 3
  echo '--- status ---'
  sudo launchctl print system/${LABEL} 2>/dev/null | grep -E 'state =|pid =' || true
  echo '--- listener ---'
  lsof -nP -iTCP:${APP_PORT} -sTCP:LISTEN || echo '(belum listen — cek /tmp/sharia_server.log)'
"

echo
echo "✓ Auto-start terpasang. Server nyala otomatis tiap Mac mini boot & restart bila crash."
echo "  Akses: http://${MACMINI_HOST}:${APP_PORT}"
echo "  Lihat log:   ssh ${MACMINI} 'tail -f /tmp/sharia_server.log'"
echo "  Restart:     ssh ${MACMINI} 'sudo launchctl kickstart -k system/${LABEL}'"
echo "  Lepas:       ssh ${MACMINI} 'sudo launchctl bootout system/${LABEL}; sudo rm ${PLIST_PATH}'"
