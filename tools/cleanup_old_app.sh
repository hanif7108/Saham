#!/usr/bin/env bash
# Cleanup old Flask application files by moving them to a backup folder

BACKUP_DIR="/Users/hanif/Saham/backup_old_flask_app"
mkdir -p "$BACKUP_DIR"

echo "Backing up old Flask application files..."

# Items to move
items=(
    "app.py"
    "canslim_screener.py"
    "trading_assistant.py"
    "fetch_dividends.py"
    "gdrive_integration.py"
    "repair_master.py"
    "run_pipeline_cron.py"
    "run_scheduler.py"
    "build_master_data.py"
    "build_master_us.py"
    "expand_sharia_list.py"
    "setup_tailscale_serve.sh"
    "setup_telegram.sh"
    "setup_macmini.sh"
    "apply_patch.sh"
    "restart_gunicorn.sh"
    "run.sh"
    "modules"
    "static"
    "templates"
    "venv"
    "sharia-trading-assistant"
    "deploy"
    "state"
    "cache"
    "exports"
    "AI Scanner"
    "Emulator"
    "PDS Trader Sakti"
    "Portofolio"
    "portfolio.csv"
    "portfolio_snapshots.csv"
    "broker_transactions.csv"
    "pegadaian_transactions.csv"
    "watchlist.txt"
    "trades_history.csv"
    "daftar_saham_syariah.csv"
    "daftar_saham_syariah_us.csv"
    "master_data_syariah.csv"
    "master_data_syariah_us.csv"
    "MM TP Baru (2).xlsx"
    "PHINTAS-Daily-Report_20260507.pdf"
    "PORTFOLIO_REPORT-179818-Hanif Andi Nugraha-20260605.PDF"
    "TC_4361751-20260526_1779795542.pdf"
    "WhatsApp Image 2026-04-30 at 07.24.09.jpeg"
    "WhatsApp Image 2026-04-30 at 07.24.49.jpeg"
    "__pycache__"
)

for item in "${items[@]}"; do
    if [ -e "/Users/hanif/Saham/$item" ]; then
        mv "/Users/hanif/Saham/$item" "$BACKUP_DIR/"
        echo "✓ Moved: $item"
    fi
done

echo "Cleanup complete. All old items moved to $BACKUP_DIR"
