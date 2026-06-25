#!/usr/bin/env bash
# Wrapper to trigger Sharia TA pipeline based on hour of day
# Used by launchd or cron

# macOS fork-safety: cegah child process (yfinance, requests, multiprocessing)
# crash dengan "+[NSCharacterSet initialize] may have been in progress in another
# thread when fork() was called" — set di-shell sebelum Python interpreter start.
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

cd "$(dirname "$0")/../.." # ke root Saham/
SAHAM_DIR="$(pwd)"

HOUR=$(date +%H)

if [ "$HOUR" -lt 12 ]; then
    echo "[$(date)] Triggering MORNING pipeline..."
    "$SAHAM_DIR/venv/bin/python3" "$SAHAM_DIR/run_pipeline_cron.py" --morning
else
    echo "[$(date)] Triggering AFTERNOON pipeline..."
    "$SAHAM_DIR/venv/bin/python3" "$SAHAM_DIR/run_pipeline_cron.py" --afternoon
fi
