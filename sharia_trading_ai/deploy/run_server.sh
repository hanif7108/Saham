#!/usr/bin/env bash
# Wrapper script to run FastAPI server and manage TradingView lifecycle
# Managed by LaunchDaemon com.sharia.trading.plist

echo "[run_server] Starting environment setup..."

# 1. Start TradingView in user hanif's GUI session
echo "[run_server] Triggering TradingView ON..."
sudo -u hanif open -a "TradingView"

# 2. Setup cleanup trap
cleanup() {
    echo "[run_server] Received termination signal. Initiating shutdown..."
    
    # Terminate uvicorn
    if [ -n "${UVICORN_PID:-}" ]; then
        echo "[run_server] Terminating uvicorn (PID: ${UVICORN_PID})..."
        kill -15 "${UVICORN_PID}" 2>/dev/null || true
    fi
    
    # Quit TradingView
    echo "[run_server] Triggering TradingView OFF..."
    sudo -u hanif osascript -e 'tell application "TradingView" to quit' 2>/dev/null || pkill -u hanif -f "TradingView" || true
    
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# 3. Start uvicorn in background
echo "[run_server] Starting uvicorn..."
/Users/hanif/Saham/sharia_trading_ai/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 80 &
UVICORN_PID=$!

# 4. Wait for uvicorn process
wait "${UVICORN_PID}"
