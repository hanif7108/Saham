#!/usr/bin/env bash
# BACKUP DATA: tarik data trading TERKINI dari Mac mini (sumber kebenaran) → MacBook.
# Mac mini = server tunggal yang menulis data. Skrip ini hanya MENYALIN ke MacBook (cadangan),
# tidak menimpa balik ke Mac mini → tidak ada konflik.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

STAMP="$(date +%Y%m%d_%H%M%S)"
echo "→ Tarik data_store dari ${MACMINI} → MacBook (backup ber-timestamp juga dibuat)"

# salinan ber-timestamp (arsip, tak menimpa yg aktif)
rsync -avz "${MACMINI}:${APP_DIR}/data_store/" "./deploy/backups/${STAMP}/"
# salinan aktif (untuk dipakai bila MacBook jalan offline)
rsync -avz "${MACMINI}:${APP_DIR}/data_store/" "./data_store/"

echo "✓ Backup data tersimpan di deploy/backups/${STAMP}/ dan data_store/ MacBook diperbarui."
