@echo off
:: ==============================================================================
:: Installer & Runner Portabel untuk Sharia Trading AI (Windows)
:: ==============================================================================
title Sharia Trading AI Portable Installer ^& Runner (Windows)
echo ========================================================
echo    ^|^|  Sharia Trading AI Portable Installer ^& Runner (Windows)  ^|^|
echo ========================================================

:: 1. Cek Python 3
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python 3 tidak ditemukan. Harap instal Python dari python.org.
    pause
    exit /b 1
)

:: 2. Cek/Instal virtualenv ^& dependensi
echo =^> Menyiapkan Virtual Environment Python...
if not exist .venv (
    python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

:: 3. Jalankan Server FastAPI
set PORT=8000
echo.
echo =^> Sharia Trading AI siap dijalankan!
echo    Aplikasi akan berjalan di http://localhost:%PORT%
echo ========================================================
uvicorn app.main:app --host 0.0.0.0 --port %PORT%
pause
