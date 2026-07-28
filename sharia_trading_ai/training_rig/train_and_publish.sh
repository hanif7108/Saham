#!/usr/bin/env bash
# Dijalankan DI RIG RTX 4090. Tarik data dari NAS -> latih -> publikasi kandidat.
# Prasyarat: repo ter-clone, venv terpasang, env DATALAKE="user@nas:/path/datalake"
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
: "${DATALAKE:?set DATALAKE=user@nas:/share/CACHEDEV1_DATA/DataLake/saham-syariah}"
STAMP=$(date +%Y%m%d_%H%M)

echo "[1/4] Tarik data mentah dari NAS..."
mkdir -p "$APP_DIR/ml_data/history"
rsync -az --partial "$DATALAKE/raw/prices/" "$APP_DIR/ml_data/history/"

echo "[2/4] Bangun dataset + latih semua varian (walk-forward sadar-biaya)..."
cd "$APP_DIR"
PY=".venv/bin/python"; [ -x ".venv312/bin/python" ] && PY=".venv312/bin/python"
PYTHONPATH=. $PY -m app.ml.dataset --screened
PYTHONPATH=. $PY -m app.ml.train                 # h5/h10/h20 + eval
PYTHONPATH=. $PY -m app.ml.train --screened --horizon 10
PYTHONPATH=. $PY -m app.ml.train --rank --horizon 10

echo "[3/4] Publikasi kandidat ke NAS models/candidate/${STAMP}_rig/ ..."
DEST="$DATALAKE/models/candidate/${STAMP}_rig/"
rsync -az app/ml/artifacts/ml_signal_h10.txt app/ml/artifacts/ml_signal_h10.meta.json \
          app/ml/artifacts/ml_rank_h10.txt   app/ml/artifacts/ml_rank_h10.meta.json  \
          "$DEST"

echo "[4/4] Selesai. REVIEW metrik dulu, lalu bila layak:"
echo "      ssh <nas> \"touch <path>/models/candidate/${STAMP}_rig/PROMOTE\""
echo "      Mac Mini akan memvalidasi & memasang pada sync 17:05 WIB berikutnya."
