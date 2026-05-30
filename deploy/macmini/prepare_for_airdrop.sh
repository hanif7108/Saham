#!/usr/bin/env bash
# Sharia TA — Prepare folder for AirDrop to Mac Mini
# ===================================================
# Membuat copy bersih di ~/Desktop/Saham_airdrop yang siap di-AirDrop.
# Mengecualikan: venv/ (~200MB), __pycache__/ (auto-generated), .env (kredensial),
#                logs/ (akan dibuat ulang), cache/ optional.
#
# Usage:
#   chmod +x deploy/macmini/prepare_for_airdrop.sh
#   ./deploy/macmini/prepare_for_airdrop.sh
#
#   Ada 2 mode:
#   ./prepare_for_airdrop.sh           # tanpa cache (paling kecil, ~100KB)
#   ./prepare_for_airdrop.sh --with-cache  # ikut cache history (lebih besar tapi tidak perlu fetch ulang)

set -e
cd "$(dirname "$0")/../.."  # ke ~/Saham
SAHAM_DIR="$(pwd)"

INCLUDE_CACHE=0
if [ "$1" == "--with-cache" ]; then
    INCLUDE_CACHE=1
fi

OUT_DIR="$HOME/Desktop/Saham_airdrop"
echo "Membuat paket di $OUT_DIR ..."

# Bersihkan kalau sudah ada
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# Files & folders WAJIB transfer
echo "Menyalin source code & data..."
rsync -a \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='logs' \
    --exclude='exports' \
    --exclude='.env' \
    --exclude='Saham_airdrop' \
    --exclude='*.pdf' \
    --exclude='CamScanner*' \
    --exclude='WhatsApp*' \
    --exclude='(Compressed)*' \
    --exclude='Sharia Investment*' \
    "$SAHAM_DIR/" "$OUT_DIR/"

# Cache: optional
if [ "$INCLUDE_CACHE" -eq 1 ]; then
    echo "Menyertakan cache (history harga 75 emiten)..."
    rsync -a "$SAHAM_DIR/cache" "$OUT_DIR/" 2>/dev/null || true
else
    echo "Cache TIDAK disertakan (akan di-fetch ulang di Mac Mini)"
    rm -rf "$OUT_DIR/cache" 2>/dev/null || true
    mkdir -p "$OUT_DIR/cache/history" "$OUT_DIR/cache/info"
fi

# Buat folder kosong yang dibutuhkan
mkdir -p "$OUT_DIR/logs" "$OUT_DIR/exports"

# Generate .env template (TANPA credentials)
cat > "$OUT_DIR/.env.template" <<'EOF'
# RENAME ke .env setelah copy ke Mac Mini, lalu isi nilai-nilainya.
# Panduan setup Telegram: lihat modules/telegram_notify.py

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Mode trading: swing | scalping | position
TRADING_MODE=scalping
EOF

# Buat README ringkas di paling atas folder
cat > "$OUT_DIR/READ_THIS_FIRST.md" <<EOF
# Sharia Trading Assistant — Mac Mini Setup

## Setelah AirDrop, di Mac Mini:

1. Pindahkan folder ini ke \`/Users/<username>/Saham\`
   \`\`\`
   mv ~/Downloads/Saham_airdrop ~/Saham
   \`\`\`

2. Rename \`.env.template\` jadi \`.env\` dan isi credentials Telegram:
   \`\`\`
   cd ~/Saham
   mv .env.template .env
   nano .env
   \`\`\`

3. Jalankan installer:
   \`\`\`
   chmod +x deploy/macmini/install_macmini.sh
   ./deploy/macmini/install_macmini.sh
   \`\`\`

4. Restart service supaya .env ke-load:
   \`\`\`
   launchctl kickstart -k gui/\$(id -u)/com.shariata.app
   \`\`\`

5. Test:
   \`\`\`
   curl -X POST http://127.0.0.1:8000/api/telegram/test
   \`\`\`

Detail lengkap: \`deploy/macmini/README.md\`
EOF

# Statistik
echo
echo "Selesai. Statistik paket:"
du -sh "$OUT_DIR"
echo
echo "Jumlah file:"
find "$OUT_DIR" -type f | wc -l
echo
echo "Top folder size:"
du -sh "$OUT_DIR"/* 2>/dev/null | sort -h | tail -10

echo
echo "=========================================="
echo "  PAKET SIAP DI-AIRDROP"
echo "=========================================="
echo
echo "  Lokasi: $OUT_DIR"
echo
echo "Cara AirDrop:"
echo "  1. Buka Finder, navigate ke ~/Desktop"
echo "  2. Klik kanan folder 'Saham_airdrop'"
echo "  3. Share → AirDrop → pilih Mac Mini Anda"
echo
echo "Atau via Terminal:"
echo "  open ~/Desktop"
echo
