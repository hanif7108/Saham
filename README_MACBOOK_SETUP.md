# Prosedur Copy Sharia Trading Assistant ke MacBook

## Ringkasan

Pipeline ini berisi aplikasi web Flask untuk analisis teknikal saham syariah (IDX & US), portofolio multi-platform, emas digital, rebalancer, dan notifikasi.

---

## 1. Siapkan Folder ZIP di MacBook Asal

Di MacBook sumber, jalankan perintah berikut di Terminal:

```bash
cd ~/Saham

# Buat zip bersih (tanpa cache, log, pycache, git)
zip -r ~/Desktop/sharia-trading-assistant.zip \
  . -x \
  "cache/*" \
  "logs/*" \
  ".git/*" \
  "*/__pycache__/*" \
  "*.pyc" \
  "*.pyo" \
  ".DS_Store" \
  "*.log" \
  "deploy/macmini/*" \
  ".env.bak.*"
```

File ZIP akan tersimpan di `~/Desktop/sharia-trading-assistant.zip`.

---

## 2. Transfer ke MacBook Tujuan

### Opsi A — AirDrop / USB / Shared Folder
Kirim file `sharia-trading-assistant.zip` ke MacBook tujuan.

### Opsi B — Command Line (scp/rsync)
Jika kedua MacBook terhubung di jaringan yang sama:

```bash
# Dari MacBook ASAL
scp ~/Desktop/sharia-trading-assistant.zip user@macbook-tujuan.local:~/Desktop/
```

---

## 3. Ekstrak & Setup di MacBook Tujuan

### 3.1 Buka Terminal di MacBook tujuan

```bash
# Buat direktori project
cd ~
mkdir -p Saham
cd Saham

# Ekstrak ZIP
unzip ~/Desktop/sharia-trading-assistant.zip
```

### 3.2 Install Python 3.10+ (jika belum ada)

```bash
# Cek versi Python
python3 --version

# Jika belum ada atau < 3.10, install via Homebrew:
brew install python@3.11

# Pastikan pip ada
python3 -m pip --version
```

### 3.3 Buat Virtual Environment (WAJIB)

```bash
cd ~/Saham
python3 -m venv venv

# Aktifkan venv
source venv/bin/activate

# (Opsional) tambahkan ke ~/.zshrc supaya auto-aktif
# echo 'source ~/Saham/venv/bin/activate' >> ~/.zshrc
```

### 3.4 Install Dependencies

```bash
# Pastikan venv aktif (prompt ada (venv) di depan)
# Kalau belum: source ~/Saham/venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Instalasi membutuhkan koneksi internet dan memakan waktu ~2-5 menit.

---

## 4. Konfigurasi Environment

### 4.1 Salin & Isi File `.env`

```bash
cd ~/Saham
cp .env .env.backup
```

Edit file `.env` dengan editor favorit (TextEdit, VS Code, nano, vim):

```bash
nano .env
```

Isi minimal yang HARUS ada:

```env
# === WAJIB ===
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_ENABLED=true

# Mode trading: swing | scalping
TRADING_MODE=swing

# === OPSIONAL (untuk AI Scanner Screenshot) ===
GEMINI_API_KEY=your_gemini_api_key_here

# === OPSIONAL (untuk Email Alert) ===
# SMTP_HOST=smtp.gmail.com
# SMTP_USER=your_email@gmail.com
# SMTP_PASS=your_app_password
# ALERT_TO=your_email@gmail.com
```

> **Cara dapatkan Telegram Bot Token & Chat ID:**
> 1. Buka Telegram → cari `@BotFather` → buat bot baru → salin token.
> 2. Kirim pesan ke bot Anda → buka `https://api.telegram.org/bot<TOKEN>/getUpdates` → cari `"chat":{"id":12345678`.

---

## 5. Jalankan Aplikasi

### Opsi A — Development Mode (python directly)

```bash
cd ~/Saham
source venv/bin/activate
python app.py
```

Aplikasi berjalan di `http://127.0.0.1:5000`

### Opsi B — Production Mode (gunicorn)

```bash
cd ~/Saham
source venv/bin/activate
gunicorn -c deploy/gunicorn_config.py app:app
```

Aplikasi berjalan di `http://127.0.0.1:8000`

### Opsi C — Background Service (launchd/macOS)

```bash
# Setup launchd plist
cp deploy/macmini/com.sharia-ta.web.plist ~/Library/LaunchAgents/

# Edit path di dalam plist sesuai lokasi project Anda:
# nano ~/Library/LaunchAgents/com.sharia-ta.web.plist

# Load service
launchctl load ~/Library/LaunchAgents/com.sharia-ta.web.plist
launchctl start com.sharia-ta.web

# Cek log
 tail -f ~/Saham/logs/launchd_stdout.log
 tail -f ~/Saham/logs/launchd_stderr.log
```

---

## 6. Akses Web Interface

Buka browser dan kunjungi:

- **Development:** `http://127.0.0.1:5000`
- **Production:** `http://127.0.0.1:8000`

---

## 7. Setup Scheduler (Opsional tapi Direkomendasikan)

Scheduler otomatis menjalankan screening harian, alert, dan snapshot portofolio:

```bash
cd ~/Saham
source venv/bin/activate

# Jalankan scheduler di background
nohup python run_scheduler.py > logs/scheduler_process.log 2>&1 &

# Atau setup cron setiap jam:
crontab -e
# Tambahkan baris:
# 0 * * * * cd ~/Saham && source venv/bin/activate && python run_pipeline_cron.py >> logs/pipeline_cron.log 2>&1
```

---

## 8. Troubleshooting Umum

### Port sudah digunakan

```bash
# Cek apa yang pakai port 5000 / 8000
lsof -nP -iTCP:5000 -sTCP:LISTEN
lsof -nP -iTCP:8000 -sTCP:LISTEN

# Kill proses lama
kill -9 <PID>
```

### Cache corrupt / data aneh

```bash
# Hapus semua cache
rm -rf ~/Saham/cache/*

# Hapus snapshot (jika ingin mulai time-series dari nol)
rm ~/Saham/portfolio_snapshots.csv
```

### Module not found

```bash
# Pastikan venv aktif
source ~/Saham/venv/bin/activate

# Re-install dependencies
pip install -r requirements.txt
```

### yfinance rate limit

```bash
# Tambah worker prefetch (default 8)
export PREFETCH_WORKERS=4
# Atau tambahkan ke .env
```

### File `.env` tidak terbaca

```bash
# Pastikan file .env ada di root project
ls -la ~/Saham/.env

# Kalau perlu, buat ulang
touch ~/Saham/.env
```

---

## 9. Struktur Direktori Penting

```
~/Saham/
├── app.py                      # Entry point Flask
├── requirements.txt            # Daftar dependencies
├── .env                        # Kredensial & konfigurasi
├── README_MACBOOK_SETUP.md     # File ini
│
├── portfolio.csv               # Portofolio manual (IDX)
├── portfolio_us.csv            # Portofolio US
├── broker_transactions.csv     # Transaksi broker
├── pegadaian_transactions.csv  # Transaksi emas Pegadaian
├── portfolio_snapshots.csv     # Snapshot harian (auto-generate)
│
├── master_data_syariah.csv     # Data master saham syariah IDX
├── master_data_syariah_us.csv  # Data master saham syariah US
├── daftar_saham_syariah.csv    # Daftar ticker syariah IDX
├── daftar_saham_syariah_us.csv # Daftar ticker syariah US
│
├── modules/                    # Modul backend
│   ├── technical_analysis.py
│   ├── asset_aggregator.py
│   ├── portfolio_snapshot.py
│   ├── pegadaian.py
│   ├── cache.py
│   └── ...
│
├── static/                     # Frontend assets
│   ├── app.js
│   ├── style.css
│   └── tradersakti_data.js
│
├── templates/
│   └── index.html
│
├── deploy/                     # Konfigurasi deployment
│   ├── gunicorn_config.py
│   ├── nginx_sharia-ta.conf
│   └── macmini/                # launchd plist untuk macOS
│
├── cache/                      # Cache yfinance (auto-generate, bisa dihapus)
├── logs/                       # Log aplikasi (auto-generate)
└── exports/                    # File export PDF/XLSX (auto-generate)
```

---

## 10. Update ke Versi Terbaru

Jika ada update dari MacBook sumber:

```bash
# 1. Hentikan service (jika running)
launchctl stop com.sharia-ta.web

# 2. Backup data pribadi
cp ~/Saham/broker_transactions.csv ~/Desktop/backup_broker_tx.csv
cp ~/Saham/portfolio.csv ~/Desktop/backup_portfolio.csv
cp ~/Saham/portfolio_us.csv ~/Desktop/backup_portfolio_us.csv
cp ~/Saham/pegadaian_transactions.csv ~/Desktop/backup_pegadaian.csv
cp ~/Saham/.env ~/Desktop/backup_env

# 3. Hapus project lama
rm -rf ~/Saham

# 4. Ekstrak ZIP baru dan restore data
# (Ulangi langkah 3.1 - 3.4 dari atas)

# 5. Restore data pribadi
cp ~/Desktop/backup_broker_tx.csv ~/Saham/broker_transactions.csv
cp ~/Desktop/backup_portfolio.csv ~/Saham/portfolio.csv
cp ~/Desktop/backup_portfolio_us.csv ~/Saham/portfolio_us.csv
cp ~/Desktop/backup_pegadaian.csv ~/Saham/pegadaian_transactions.csv
cp ~/Desktop/backup_env ~/Saham/.env

# 6. Restart service
launchctl start com.sharia-ta.web
```

---

**Selesai!** Aplikasi siap digunakan di MacBook tujuan.
