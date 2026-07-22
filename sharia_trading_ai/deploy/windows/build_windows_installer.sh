#!/usr/bin/env bash
# ==============================================================================
# Script untuk Membuat Installer Windows MSI (.msi) di macOS
# ==============================================================================
set -euo pipefail

echo "========================================================"
echo "   ☪  Sharia Trading AI MSI Installer Builder for Windows"
echo "========================================================"

# 1. Pastikan msitools terinstall via Homebrew
if ! command -v wixl &>/dev/null; then
    echo "=> Menginstal msitools (wixl) via Homebrew..."
    brew install msitools
else
    echo "✅ msitools (wixl) sudah terpasang."
fi

# 2. Definisikan folder kerja
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="${PROJECT_DIR}/dist/windows_app"
CACHE_DIR="${SCRIPT_DIR}/cache"

echo "Project dir: ${PROJECT_DIR}"
echo "Build dir: ${BUILD_DIR}"

# Buat folder sementara
mkdir -p "${CACHE_DIR}/wheels"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/python"

# 3. Unduh Portable Python 3.12 untuk Windows jika belum ada di cache
PYTHON_ZIP="python-3.12.3-embed-amd64.zip"
PYTHON_URL="https://www.python.org/ftp/python/3.12.3/${PYTHON_ZIP}"

if [ ! -f "${CACHE_DIR}/${PYTHON_ZIP}" ]; then
    echo "=> Mengunduh portable Python 3.12 untuk Windows (AMD64)..."
    curl -L "${PYTHON_URL}" -o "${CACHE_DIR}/${PYTHON_ZIP}"
else
    echo "✅ Menggunakan Python zip portabel dari cache."
fi

# Ekstrak Python
echo "=> Mengekstrak Python portabel..."
unzip -q "${CACHE_DIR}/${PYTHON_ZIP}" -d "${BUILD_DIR}/python"

# Konfigurasi agar Python portabel melacak Lib/site-packages
echo "=> Mengkonfigurasi pathing Python..."
echo -e "python312.zip\n.\nsite-packages\nimport site" > "${BUILD_DIR}/python/python312._pth"

# 4. Unduh Wheels Windows (win_amd64) untuk dependencies
echo "=> Mengunduh Windows wheels untuk requirements.txt..."
# Buat requirements khusus Windows tanpa uvicorn[standard] (karena uvloop tidak dukung Windows)
sed 's/uvicorn\[standard\]/uvicorn/g' "${PROJECT_DIR}/requirements.txt" > "${CACHE_DIR}/requirements_win.txt"
# Gunakan pip dari venv macOS untuk mengunduh versi Windows
"${PROJECT_DIR}/.venv/bin/pip" download \
    --only-binary=:all: \
    --platform win_amd64 \
    --python-version 312 \
    --implementation cp \
    --abi cp312 \
    -r "${CACHE_DIR}/requirements_win.txt" \
    -d "${CACHE_DIR}/wheels"

# 5. Ekstrak seluruh wheels ke folder site-packages Python portabel
echo "=> Mengekstrak wheels ke site-packages portabel..."
mkdir -p "${BUILD_DIR}/python/site-packages"
for whl in "${CACHE_DIR}/wheels"/*.whl; do
    unzip -o -q "${whl}" -d "${BUILD_DIR}/python/site-packages"
done

# Kompresi site-packages menjadi zip untuk mengurangi file count
echo "=> Mengompresi site-packages menjadi zip..."
cd "${BUILD_DIR}/python"
zip -q -r site-packages.zip site-packages
rm -rf site-packages
cd "${PROJECT_DIR}"

# 6. Salin kode aplikasi utama
echo "=> Menyalin kode program Saham..."
cp -R "${PROJECT_DIR}/app" "${BUILD_DIR}/app"

# Bikin folder data_store & data_cache kosong di installer agar siap pakai
mkdir -p "${BUILD_DIR}/data_store"
mkdir -p "${BUILD_DIR}/data_cache"

# Salin config data_store awal jika ada
if [ -d "${PROJECT_DIR}/data_store" ]; then
    cp -R "${PROJECT_DIR}/data_store"/* "${BUILD_DIR}/data_store/" || true
fi

# Salin environment (.env)
if [ -f "${PROJECT_DIR}/.env" ]; then
    cp "${PROJECT_DIR}/.env" "${BUILD_DIR}/.env"
else
    # default template
    echo "TRADING_MODE=swing" > "${BUILD_DIR}/.env"
fi

# 7. Salin skrip peluncur Windows
echo "=> Menyalin skrip kontrol Windows..."
cp "${SCRIPT_DIR}/StartApp.vbs" "${BUILD_DIR}/StartApp.vbs"
cp "${SCRIPT_DIR}/StopApp.bat" "${BUILD_DIR}/StopApp.bat"

# 8. Hasilkan WiX XML berkas (.wxs)
echo "=> Membuat berkas konfigurasi WiX (.wxs)..."
python3 "${SCRIPT_DIR}/generate_wxs.py" "${BUILD_DIR}" "${PROJECT_DIR}/sharia_trading_ai.wxs"

# 9. Kompilasi menjadi berkas installer .msi
echo "=> Mengompilasi menjadi .msi dengan wixl..."
cd "${PROJECT_DIR}"
wixl -o "${PROJECT_DIR}/sharia_trading_ai.msi" sharia_trading_ai.wxs

# Bersihkan berkas wxs sementara
rm -rf sharia_trading_ai.wxs

echo "========================================================"
echo "✅ SUKSES! Installer Windows telah siap!"
echo "   Output: ${PROJECT_DIR}/sharia_trading_ai.msi"
echo "========================================================"
