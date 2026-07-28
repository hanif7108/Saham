#!/usr/bin/env bash
# Retrain bulanan model ML sinyal (LightGBM) — dijalankan launchd di Mac Mini.
#   1. Fetch data historis yfinance terbaru (incremental, cache 20 jam)
#   2. Rakit ulang dataset panel fitur+label
#   3. Walk-forward eval + latih artifact final (app/ml/artifacts/)
#   4. Restart service agar uvicorn memuat artifact baru
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$APP_DIR/.venv/bin/python"
LOG_DIR="$APP_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/ml_retrain_$(date +%Y%m%d).log"

cd "$APP_DIR"
{
  echo "=== ML retrain mulai: $(date) ==="
  PYTHONPATH="$APP_DIR" "$VENV" -m app.ml.data_fetch --force
  PYTHONPATH="$APP_DIR" "$VENV" -m app.ml.dataset
  PYTHONPATH="$APP_DIR" "$VENV" -m app.ml.train
  echo "=== Selesai training: $(date) ==="

  # Lingkaran belajar: evaluasi prediksi live yang jatuh tempo + laporan
  # track record (prediksi vs realisasi) sebagai catatan kualitas bulanan.
  PYTHONPATH="$APP_DIR" "$VENV" -m app.ml.tracker --evaluate --report || true

  # Restart service supaya artifact baru dimuat (uvicorn cache model di memori).
  # Nama label mengikuti plist yang aktif di Mac Mini.
  for LABEL in com.shariata.app com.sharia.trading; do
    if launchctl list "$LABEL" >/dev/null 2>&1; then
      echo "Restart $LABEL..."
      launchctl kickstart -k "gui/$(id -u)/$LABEL" 2>/dev/null \
        || sudo launchctl kickstart -k "system/$LABEL" 2>/dev/null \
        || echo "PERINGATAN: gagal restart $LABEL — restart manual diperlukan"
      break
    fi
  done
  echo "=== ML retrain selesai: $(date) ==="
} >> "$LOG" 2>&1
