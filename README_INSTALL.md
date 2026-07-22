# Sharia Trading Assistant — Install di Mac Mini (24/7)

Panduan deployment di Mac Mini untuk operasi 24 jam non-stop. Snapshot ini
sudah include semua data trading Anda (portfolio, broker, Pegadaian), master
data fundamental ter-update, dan kredensial Telegram. Tinggal extract,
install dependencies, lalu register launchd.

## TL;DR (5 menit setup)

```bash
# 1. Extract ke ~/Saham/
unzip saham_pipeline_clone_YYYYMMDD.zip -d ~/Saham

# 2. Install Python deps (sekali saja)
cd ~/Saham
./run.sh --setup     # build venv + pip install requirements

# 3. Register launchd untuk auto-start 24/7
cp deploy/macmini/com.shariata.app.plist      ~/Library/LaunchAgents/
cp deploy/macmini/com.shariata.pipeline.plist ~/Library/LaunchAgents/
cp deploy/macmini/com.shariata.caffeinate.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.shariata.app.plist
launchctl load ~/Library/LaunchAgents/com.shariata.pipeline.plist
launchctl load ~/Library/LaunchAgents/com.shariata.caffeinate.plist

# 4. Test
sleep 5
curl -s http://127.0.0.1:8000/api/dashboard | python3 -m json.tool | head -20
```

Buka `http://<mac-mini-ip>:8000/` dari browser MacBook untuk akses dashboard.

---

## Prasyarat Mac Mini

- macOS 12+ (Monterey atau lebih baru)
- Python 3.11 (kalau belum: `brew install python@3.11`)
- Disk space: ~500 MB (venv + cache + logs growth)
- Network: koneksi internet stabil (yfinance, Google Finance, Pegadaian harga emas)
- User account dengan auto-login agar launchd menjalankan agent saat boot

## Struktur Folder Setelah Extract

```
~/Saham/
├── app.py                          # Main Flask app
├── modules/                        # Engine: scoring, decision, rebalancer, pegadaian, asset_aggregator
├── templates/index.html            # Frontend SPA
├── static/                         # CSS + JS
├── deploy/
│   ├── gunicorn_config.py          # Gunicorn workers + scheduler hook
│   ├── requirements.txt            # Python dependencies
│   └── macmini/
│       ├── com.shariata.app.plist        # LaunchAgent: gunicorn 24/7
│       ├── com.shariata.pipeline.plist   # LaunchAgent: cron pagi (08:30) + sore (16:00)
│       ├── com.shariata.caffeinate.plist # Mencegah Mac Mini sleep
│       ├── trigger_pipeline.sh           # Wrapper pipeline
│       └── install_macmini.sh            # Helper install all-in-one
├── daftar_saham_syariah.csv        # 75 ticker syariah (universe)
├── master_data_syariah.csv         # Snapshot fundamental terbaru
├── portfolio.csv                   # Holdings saham (auto-sync dari broker_tx)
├── broker_transactions.csv         # Audit trail Bibit
├── pegadaian_transactions.csv      # Tabungan emas digital
├── .env                            # Telegram bot token & chat_id (PRIVATE!)
├── run.sh                          # Quick-start manual (port 8000)
├── restart_gunicorn.sh             # Restart bersih (kill + start)
└── run_pipeline_cron.py            # Pipeline morning/afternoon
```

## Step-by-Step Install

### 1. Extract zip

```bash
cd ~
unzip /path/to/saham_pipeline_clone_YYYYMMDD.zip -d Saham
cd Saham
```

### 2. Install Python venv + dependencies

```bash
./run.sh --setup
```

Skrip ini check Python 3.9+, bikin venv di folder Saham, lalu pip install
flask, gunicorn, pandas, yfinance, apscheduler, openpyxl, reportlab, requests,
beautifulsoup4. Estimasi waktu: ~2 menit.

### 3. Edit plist (kalau username Mac Mini bukan `hanif`)

File plist hard-code path `/Users/hanif/Saham/`. Kalau Mac Mini Anda pakai
username berbeda:

```bash
sed -i '' 's|/Users/hanif|/Users/<YOUR_USERNAME>|g' deploy/macmini/*.plist
```

### 4. Register launchd agents

```bash
cp deploy/macmini/com.shariata.app.plist        ~/Library/LaunchAgents/
cp deploy/macmini/com.shariata.pipeline.plist   ~/Library/LaunchAgents/
cp deploy/macmini/com.shariata.caffeinate.plist ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.shariata.app.plist
launchctl load ~/Library/LaunchAgents/com.shariata.pipeline.plist
launchctl load ~/Library/LaunchAgents/com.shariata.caffeinate.plist
```

Apa yang masing-masing lakukan:

| Plist | Fungsi |
|---|---|
| `com.shariata.app` | Jalankan gunicorn port 8000, auto-restart kalau crash. Auto-start saat user login. |
| `com.shariata.pipeline` | Trigger `run_pipeline_cron.py --morning` setiap 08:30 WIB Senin-Jumat, `--afternoon` setiap 16:00 WIB. |
| `com.shariata.caffeinate` | Jalankan `caffeinate` agar Mac Mini tidak sleep — wajib untuk 24/7. |

### 5. Verifikasi

```bash
launchctl list | grep shariata
lsof -i :8000
curl -s http://127.0.0.1:8000/api/dashboard | python3 -m json.tool | head -30
tail -f logs/gunicorn_error.log
```

### 6. Akses dari device lain di network rumah

Default gunicorn bind ke `127.0.0.1:8000` (localhost only). Untuk akses dari
MacBook/iPhone di WiFi yang sama, edit `deploy/gunicorn_config.py`:

```python
bind = "0.0.0.0:8000"   # ganti dari 127.0.0.1
```

Cek IP Mac Mini: `ipconfig getifaddr en0` (ethernet) atau `en1` (wifi).
Akses: `http://192.168.x.x:8000/` dari device lain.

PENTING keamanan: kalau Mac Mini di-expose ke internet (port forward), WAJIB
pakai nginx reverse-proxy dengan SSL + basic auth. Lihat
`deploy/nginx_sharia-ta.conf` sebagai template.

## Maintenance & Operasi

### Restart manual setelah update kode

```bash
bash ~/Saham/restart_gunicorn.sh
```

Skrip ini idempotent — bisa dijalankan kapan saja. Akan kill gunicorn lama,
pre-flight import check, lalu start baru.

### Update master data manual (di luar jadwal cron)

```bash
~/Saham/venv/bin/python3 ~/Saham/build_master_data.py
```

Atau via UI: klik tombol "⚙️ Update Master" di header dashboard.

### Restart launchd agent saja

```bash
launchctl unload ~/Library/LaunchAgents/com.shariata.app.plist
launchctl load ~/Library/LaunchAgents/com.shariata.app.plist
```

### Backup data trading

Selalu backup 3 CSV ini secara berkala:

```bash
tar czf saham_backup_$(date +%Y%m%d).tar.gz \
    ~/Saham/portfolio.csv \
    ~/Saham/broker_transactions.csv \
    ~/Saham/pegadaian_transactions.csv
```

### Lihat log

```bash
# Pipeline cron morning/afternoon
tail -f ~/Saham/logs/pipeline_cron.log

# Gunicorn web server
tail -f ~/Saham/logs/gunicorn_error.log
tail -f ~/Saham/logs/gunicorn_access.log

# Scheduler internal (alert scan 30 menit)
tail -f ~/Saham/logs/scheduler.log
```

## Troubleshooting

### Endpoint /api/dashboard return 404

Gunicorn pakai kode lama. Pakai `restart_gunicorn.sh` (bukan SIGHUP — karena
`preload_app=True` di gunicorn_config.py membuat SIGHUP tidak reload code).

### objc fork() crash di launchd_stderr.log

Sudah di-fix dengan `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` di kedua plist
(`com.shariata.app.plist` dan `com.shariata.pipeline.plist`). Kalau muncul lagi,
verify env var ada di plist:

```bash
grep OBJC_DISABLE ~/Library/LaunchAgents/com.shariata.app.plist
```

### Telegram brief tidak terkirim

Cek `.env` di Mac Mini:

```bash
cat ~/Saham/.env
```

Pastikan `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, dan `TELEGRAM_ENABLED=true`
ada. Lalu restart gunicorn dan trigger pipeline manual untuk test:

```bash
~/Saham/venv/bin/python3 ~/Saham/run_pipeline_cron.py --morning
```

### Port 8000 sudah dipakai aplikasi lain

Edit `deploy/gunicorn_config.py` ganti port ke 8001 atau lainnya:

```python
bind = "127.0.0.1:8001"
```

Lalu restart agent.

### Mac Mini sleep terus walau caffeinate ter-load

Buka System Settings → Battery / Energy Saver:
- "Prevent automatic sleeping when display is off": ON
- "Wake for network access": ON

## Versi & Snapshot

Snapshot ini dibuat: 2026-05-24

Komponen utama:
- Flask 3.x + gunicorn 25 (preload_app=True, 4 worker gthread)
- Python 3.9+ (recommended 3.11)
- Engine: scoring (CAN SLIM + 6 Magic Numbers), decision (BUY/SELL/HOLD), rebalancer (alokasi saham/emas/cash), pegadaian (emas digital), asset_aggregator (single source of truth)
- Frontend: SPA Tailwind-like vanilla CSS + Chart.js
- Storage: CSV files (portfolio, broker_transactions, pegadaian_transactions, master_data, daftar_saham_syariah)
