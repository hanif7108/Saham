#!/usr/bin/env bash
# Script to configure Mac mini power, LaunchDaemons, and Tailscale Serve for Sharia Trading AI
# Run this on the Mac mini with sudo!

echo "1. Configuring Mac mini power schedule..."

# Set wake schedule: Monday to Friday at 03:00:00 local time (07:00 WIB)
sudo pmset repeat wake MTWRF 03:00:00

# Enable idle sleep: put system to sleep after 15 minutes of idle time
sudo pmset -a sleep 15
sudo pmset -a disksleep 10
sudo pmset -a displaysleep 10

echo "Current schedule configuration:"
pmset -g sched

echo "Current power settings:"
pmset -g

echo "--------------------------------------------------"
echo "2. Installing & Loading FastAPI LaunchDaemon (com.sharia.trading)..."

LABEL="com.sharia.trading"
PLIST_PATH="/Library/LaunchDaemons/${LABEL}.plist"

# Stop any running uvicorn process
pkill -f 'uvicorn app.main' 2>/dev/null || true

# Copy plist to system LaunchDaemons
if [ -f /tmp/${LABEL}.plist ]; then
    sudo mv /tmp/${LABEL}.plist "${PLIST_PATH}"
    sudo chown root:wheel "${PLIST_PATH}"
    sudo chmod 644 "${PLIST_PATH}"
    echo "✓ Plist moved to ${PLIST_PATH}"
fi

# Load service
sudo launchctl bootout system/${LABEL} 2>/dev/null || true
sudo launchctl bootstrap system "${PLIST_PATH}"
echo "✓ LaunchDaemon bootstrapped"

# Wait a brief moment for the service to start
sleep 3

echo "--------------------------------------------------"
echo "3. Configuring Tailscale Serve (Forward HTTPS 443 -> HTTP 80)..."

# Reset any previous config
sudo /Applications/Tailscale.app/Contents/MacOS/Tailscale serve reset 2>/dev/null || true

# Forward HTTPS 443 -> HTTP 80
sudo /Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg --https 443 80

echo "Current Tailscale Serve status:"
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status

echo "--------------------------------------------------"
echo "4. Verifying Listeners..."
lsof -nP -iTCP:80 -sTCP:LISTEN || echo "⚠️ Server not listening on port 80 - check /tmp/sharia_server.log"
