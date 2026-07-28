#!/usr/bin/env bash
# KOLEKSI DATA HARIAN — dijalankan DI RIG RTX 4090 (systemd timer 17:20 WIB).
# Peran (keputusan 2026-07-28): rig = mesin produksi data (broadband kantor,
# outbound-only, tulis langsung ke NAS se-LAN); Mac Mini = web service.
set -uo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
: "${DATALAKE:?set DATALAKE=user@nas:/path/datalake}"
PY="$APP_DIR/.venv/bin/python"; [ -x "$APP_DIR/.venv312/bin/python" ] && PY="$APP_DIR/.venv312/bin/python"
LOG="$APP_DIR/collect.log"

{
  echo "=== collect mulai: $(date -u +%FT%TZ) ==="
  # 1. Snapshot keanggotaan + fetch OHLCV 844 ticker (incremental 20 jam)
  PYTHONPATH="$APP_DIR" "$PY" -m app.ml.universe_collector --fetch

  # 2. Tulis ke datalake (LAN — hitungan detik)
  rsync -az --partial "$APP_DIR/ml_data/history/"            "$DATALAKE/raw/prices/"
  rsync -az --partial "$APP_DIR/ml_data/universe_snapshots/" "$DATALAKE/raw/universe/"

  # 3. State utk observabilitas (dibaca siapa pun dari NAS)
  printf '{"last_success":"%s","host":"rig-rtx4090"}\n' "$(TZ=Asia/Jakarta date +%FT%T+07:00)" \
    | ssh "${DATALAKE%%:*}" "cat > '${DATALAKE#*:}/logs/collect_state.json'"
  echo "=== collect selesai: $(date -u +%FT%TZ) ==="
} >> "$LOG" 2>&1
