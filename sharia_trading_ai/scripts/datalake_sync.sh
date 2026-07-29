#!/usr/bin/env bash
# Datalake Trading Saham Sharia — sinkronisasi Mac Mini -> NAS (via Tailscale).
#
# Desain (Mac Mini & NAS BEDA lokasi, latensi 300-1000ms):
#   - Aplikasi TIDAK PERNAH membaca/menulis NAS saat runtime. Data panas
#     tetap lokal; NAS = arsip datalake (append-only, basis training AI).
#   - rsync incremental over SSH: hemat bandwidth, aman putus di tengah
#     (--partial), dan kalau NAS offline script keluar rapi — data menunggu
#     lokal sampai sync berikutnya.
#   - Transfer via SSH key (tanpa password). Pasang sekali:
#       ssh-copy-id qnap@100.70.97.42
#
# Mode:
#   datalake_sync.sh            # collect + snapshot + push + ingest (harian 17:05)
#   datalake_sync.sh snapshot   # hanya kumpulkan snapshot harian lokal
#   datalake_sync.sh collect    # snapshot universe penuh + fetch OHLCV 844 ticker
#   datalake_sync.sh push       # hanya push ke NAS
#   datalake_sync.sh ingest     # tarik kandidat model dari NAS -> validasi -> promosi
#   datalake_sync.sh pull       # restore datalake NAS -> lokal (disaster recovery)
set -uo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ML_DATA="$APP_DIR/ml_data"
STATE="$ML_DATA/datalake_state.json"
LOG_DIR="$APP_DIR/logs"; mkdir -p "$LOG_DIR" "$ML_DATA/decisions_snapshots" "$ML_DATA/fundamentals_snapshots"
LOG="$LOG_DIR/datalake_sync.log"

# --- konfigurasi (override via env) ---
NAS_USER="${DATALAKE_USER:-qnap}"
NAS_HOST="${DATALAKE_HOST:-100.70.97.42}"
NAS_ROOT="${DATALAKE_REMOTE:-/share/CACHEDEV1_DATA/DataLake/saham-syariah}"
SSH_OPTS="-o ConnectTimeout=15 -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
RSYNC="rsync -az --partial --timeout=60 -e \"ssh $SSH_OPTS\""

ts(){ date +"%Y-%m-%dT%H:%M:%S%z"; }
log(){ echo "[$(ts)] $*" >> "$LOG"; }

write_state(){ # $1=status $2=pesan
  python3 - "$1" "$2" <<'PY'
import json, sys, datetime, os
state_path = os.environ["STATE"]
d = {}
try: d = json.load(open(state_path))
except Exception: pass
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).isoformat(timespec="seconds")
d["last_run"] = now
d["last_status"] = sys.argv[1]
d["last_message"] = sys.argv[2]
if sys.argv[1] == "ok": d["last_success"] = now
json.dump(d, open(state_path, "w"), indent=1)
PY
}
export STATE

snapshot(){
  local today; today=$(date +%Y-%m-%d)
  # 1. Snapshot keputusan harian (payload /api/decisions dari cache app lokal)
  if curl -s --max-time 90 "http://localhost/api/decisions" -o "$ML_DATA/decisions_snapshots/decisions_${today}.json" 2>/dev/null \
     && [ -s "$ML_DATA/decisions_snapshots/decisions_${today}.json" ]; then
    log "snapshot decisions ${today} OK"
  else
    rm -f "$ML_DATA/decisions_snapshots/decisions_${today}.json"
    log "snapshot decisions ${today} GAGAL (app tidak jalan?)"
  fi
  # 2. Snapshot fundamental terkurasi (kecil, berharga sebagai point-in-time!)
  cp "$APP_DIR/app/data/master_data_syariah.csv" \
     "$ML_DATA/fundamentals_snapshots/master_data_syariah_${today}.csv" 2>/dev/null \
     && log "snapshot fundamental ${today} OK"
}

collect(){
  # Universe penuh IDX (~844 ticker): snapshot keanggotaan + OHLCV incremental.
  # Universe TRADING tetap 75 terkurasi — ini murni pengayaan DATALAKE.
  log "collect universe penuh mulai"
  PYTHONPATH="$APP_DIR" "$APP_DIR/.venv/bin/python" -m app.ml.universe_collector --fetch \
    >>"$LOG" 2>&1 && log "collect universe penuh OK" || log "collect universe GAGAL (lanjut)"
}

ingest(){
  # Tarik kandidat model dari NAS (hasil training RTX 4090) -> validasi -> promosi.
  mkdir -p "$ML_DATA/candidate_models"
  eval "$RSYNC "$NAS_USER@$NAS_HOST:$NAS_ROOT/models/candidate/" $ML_DATA/candidate_models/" >>"$LOG" 2>&1 \
    || { log "ingest: candidate dir belum ada di NAS (lewati)"; return 0; }
  PYTHONPATH="$APP_DIR" "$APP_DIR/.venv/bin/python" -m app.ml.model_ingest >>"$LOG" 2>&1 \
    && log "ingest kandidat model selesai" || log "ingest GAGAL"
  # dorong balik status (PROMOTED_AT / penghapusan marker) agar rig tahu
  eval "$RSYNC $ML_DATA/candidate_models/ "$NAS_USER@$NAS_HOST:$NAS_ROOT/models/candidate/"" >>"$LOG" 2>&1 || true
}

push(){
  # sanity: NAS terjangkau?
  if ! ssh $SSH_OPTS "$NAS_USER@$NAS_HOST" "mkdir -p '$NAS_ROOT'/{raw/prices,raw/fundamentals,curated/datasets,curated/walkforward,predictions/decisions,models,logs}" >>"$LOG" 2>&1; then
    log "PUSH DIBATALKAN: NAS tidak terjangkau / SSH key belum terpasang"
    write_state "error" "NAS tidak terjangkau / SSH key belum terpasang (ssh-copy-id $NAS_USER@$NAS_HOST)"
    return 1
  fi
  local fail=0 month; month=$(date +%Y-%m)
  R(){ eval "$RSYNC $1 \"$NAS_USER@$NAS_HOST:$2\"" >>"$LOG" 2>&1 || { log "rsync gagal: $1"; fail=1; }; }

  # raw/prices & raw/universe kini MILIK RIG (koleksi 17:20 WIB dari kantor,
  # LAN ke NAS). Mini tidak menulis zona itu lagi agar tidak menimpa data
  # yang lebih segar. (Pull utk retrain lokal tetap tersedia: mode pull.)
  R "$ML_DATA/fundamentals_snapshots/"        "$NAS_ROOT/raw/fundamentals/"
  [ -f "$ML_DATA/dataset.parquet" ] && \
  R "$ML_DATA/dataset.parquet"                "$NAS_ROOT/curated/datasets/dataset_latest.parquet"
  [ -d "$ML_DATA/walkforward" ] && \
  R "$ML_DATA/walkforward/"                   "$NAS_ROOT/curated/walkforward/"
  [ -f "$ML_DATA/ml_track.parquet" ] && \
  R "$ML_DATA/ml_track.parquet"               "$NAS_ROOT/predictions/ml_track.parquet"
  [ -f "$ML_DATA/ml_track_summary.json" ] && \
  R "$ML_DATA/ml_track_summary.json"          "$NAS_ROOT/predictions/ml_track_summary.json"
  [ -f "$ML_DATA/intraday_scans.parquet" ] && \
  R "$ML_DATA/intraday_scans.parquet"         "$NAS_ROOT/predictions/intraday_scans.parquet"
  R "$ML_DATA/decisions_snapshots/"           "$NAS_ROOT/predictions/decisions/"
  [ -d "$ML_DATA/portfolio_snapshots" ] && \
  R "$ML_DATA/portfolio_snapshots/"           "$NAS_ROOT/predictions/portfolio/"
  R "$APP_DIR/app/ml/artifacts/"              "$NAS_ROOT/models/$month/"
  [ -f "$ML_DATA/audit_summary.json" ] && \
  R "$ML_DATA/audit_summary.json"             "$NAS_ROOT/logs/audit_summary.json"

  if [ "$fail" -eq 0 ]; then
    log "PUSH OK -> $NAS_HOST:$NAS_ROOT"
    write_state "ok" "sync lengkap ke $NAS_HOST"
    prune_local
  else
    write_state "partial" "sebagian rsync gagal — lihat logs/datalake_sync.log"
  fi
}

prune_local(){
  # Hemat storage Mac Mini: snapshot lokal > 14 hari dihapus SETELAH sukses
  # tersalin ke NAS (arsip lengkap tetap ada di datalake).
  find "$ML_DATA/decisions_snapshots"    -name "*.json" -mtime +14 -delete 2>/dev/null
  find "$ML_DATA/fundamentals_snapshots" -name "*.csv"  -mtime +14 -delete 2>/dev/null
  log "prune lokal (>14 hari) selesai"
}

pull(){
  log "PULL datalake dari NAS -> lokal (restore)"
  eval "$RSYNC \"$NAS_USER@$NAS_HOST:$NAS_ROOT/raw/prices/\" $ML_DATA/history/" >>"$LOG" 2>&1
  eval "$RSYNC \"$NAS_USER@$NAS_HOST:$NAS_ROOT/predictions/ml_track.parquet\" $ML_DATA/ml_track.parquet" >>"$LOG" 2>&1
  log "PULL selesai"
}

case "${1:-all}" in
  snapshot) snapshot ;;
  collect)  collect ;;
  push)     push ;;
  ingest)   ingest ;;
  pull)     pull ;;
  all)      snapshot; push; ingest ;;   # collect 844 kini tugas RIG (17:20 WIB)
  *) echo "mode: snapshot|collect|push|ingest|pull|all"; exit 2 ;;
esac
