# Mac Mini 24/7 Deployment Guide

Panduan deploy Sharia Trading Assistant di Mac Mini sebagai server pribadi 24 jam, dengan notifikasi Telegram untuk scalping.

## Yang Akan Dibangun

```
Mac Mini (selalu menyala)
├── launchd: com.shariata.app          ← Flask + Gunicorn (port 8000), auto-restart on crash
├── launchd: com.shariata.caffeinate   ← cegah Mac sleep
├── launchd: com.shariata.logrotate    ← rotate log >10MB tiap pukul 03:00
└── pmset:    sleep 0, autorestart on power failure
```

Setiap **5 menit** (scalping mode) selama jam pasar **09:00–15:00 WIB Senin–Jumat**, scheduler internal scan portfolio + 75 emiten, dan kalau ada alert → langsung **kirim ke Telegram Anda**.

## Prasyarat

- Mac Mini (Apple Silicon atau Intel) — macOS 12+
- Login otomatis aktif (System Settings → Users & Groups → Auto-login)
- Internet 24/7 (kabel disarankan)
- Bot Telegram sudah dibuat (lihat `modules/telegram_notify.py` untuk panduan @BotFather)

## Instalasi (1 perintah)

Salin folder `Saham` ke Mac Mini di `/Users/<username>/Saham`, lalu:

```bash
cd ~/Saham
chmod +x deploy/macmini/install_macmini.sh
./deploy/macmini/install_macmini.sh
```

Script akan:
1. Bikin venv + install dependencies
2. Buat `.env` template
3. Pasang launchd services (app + caffeinate + logrotate)
4. Set pmset (sleep=0, auto-restart on power)
5. Verify HTTP endpoint

## Setelah Install

### 1. Konfigurasi Telegram di `.env`

```bash
nano ~/Saham/.env
```

Isi:
```
TELEGRAM_BOT_TOKEN=7891234567:AAH-xxxxxxxxxxxx
TELEGRAM_CHAT_ID=123456789
TRADING_MODE=scalping
```

Trading mode pilihan:
| Mode | CL | TP | Scan tiap | Cocok untuk |
|---|---|---|---|---|
| `swing` | -3% | +6% | 30 menit | Hold beberapa hari (Taichi default) |
| `scalping` | -1% | +2% | **5 menit** | Intraday cepat (yang Anda mau) |
| `position` | -7% | +20% | 60 menit | Hold mingguan (O'Neil) |

### 2. Restart service supaya `.env` ke-load:

```bash
launchctl kickstart -k gui/$(id -u)/com.shariata.app
```

### 3. Test Telegram:

```bash
curl -X POST http://127.0.0.1:8000/api/telegram/test
```

Kalau Telegram Anda dapat pesan "✅ Sharia Trading Assistant — Test", **berhasil**.

## Akses dari Device Lain (HP/laptop di rumah)

Default: hanya bisa diakses dari Mac Mini sendiri (`127.0.0.1`). Untuk akses dari HP/laptop di Wi-Fi yang sama:

### Option A: Bind ke 0.0.0.0 (akses LAN)

Edit `deploy/gunicorn_config.py`:
```python
bind = "0.0.0.0:8000"
```

Lalu:
```bash
launchctl kickstart -k gui/$(id -u)/com.shariata.app
```

Cek IP Mac Mini:
```bash
ipconfig getifaddr en0
# Misal: 192.168.1.10
```

Akses dari HP: `http://192.168.1.10:8000`

### Option B: Tailscale (akses dari mana saja, aman)

```bash
brew install tailscale
sudo tailscaled install-system-daemon
tailscale up
```

Akses dari device manapun via Tailscale IP — **tidak perlu open port public**.

## Manajemen Service

```bash
# Status semua services
launchctl list | grep shariata

# Stop app
launchctl unload ~/Library/LaunchAgents/com.shariata.app.plist

# Start app
launchctl load ~/Library/LaunchAgents/com.shariata.app.plist

# Restart app (cara paling cepat)
launchctl kickstart -k gui/$(id -u)/com.shariata.app

# Lihat log realtime
tail -f ~/Saham/logs/launchd_stderr.log
tail -f ~/Saham/logs/scheduler.log
tail -f ~/Saham/logs/alerts.log

# Cek HTTP health
curl http://127.0.0.1:8000/api/cache/stats
curl http://127.0.0.1:8000/api/trading_mode
```

## Power Settings (Verify)

```bash
pmset -g | grep -E "sleep|disksleep|autorestart|womp"
```

Harusnya:
- `sleep 0`
- `disksleep 0`
- `autorestart 1` (auto-restart on power failure)
- `womp 1` (wake on magic packet)

## Schedule Internal (otomatis berjalan setelah install)

| Job | Trigger | Aksi |
|---|---|---|
| **Intraday alert scan** | Setiap 5 menit (scalping) jam 09–15 WIB Senin-Jumat | Scan + push ke Telegram |
| **Morning brief** | 08:30 WIB Senin-Jumat | Kirim verdict + portfolio ke Telegram |
| **Master data rebuild** | 06:00 WIB Senin-Jumat | Refresh fundamental yfinance |
| **Log rotation** | 03:00 setiap hari | File >10MB di-rotate, file >30 hari dihapus |

## Workflow Scalping di Mac Mini

```
06:00 → master data refresh (background)
08:30 → Telegram morning brief: verdict + posisi
09:00 → IHSG buka. Scheduler aktif.
09:05, 09:10, 09:15... → scan tiap 5 menit
        Kalau detect: CUT_LOSS / TAKE_PROFIT / STRONG_BUY → push Telegram
        Anda buka HP → action di sekuritas
15:00 → IHSG tutup. Scheduler idle sampai besok.
03:00 → log rotation
```

## Troubleshooting

**Service tidak start:**
```bash
# Cek error
tail -50 ~/Saham/logs/launchd_stderr.log

# Reload manual
launchctl unload ~/Library/LaunchAgents/com.shariata.app.plist
launchctl load ~/Library/LaunchAgents/com.shariata.app.plist
```

**Telegram tidak masuk:**
```bash
# Verify token
curl -X POST http://127.0.0.1:8000/api/telegram/test

# Cek konfigurasi
curl http://127.0.0.1:8000/api/telegram/status
```

**Mac Mini malah sleep:**
```bash
# Verify caffeinate running
launchctl list | grep caffeinate
ps aux | grep caffeinate

# Kalau hilang: load ulang
launchctl load ~/Library/LaunchAgents/com.shariata.caffeinate.plist
```

**Port 8000 conflict:**
Edit `deploy/gunicorn_config.py`:
```python
bind = "127.0.0.1:8888"
```
Restart service.

**Mau update kode:**
```bash
cd ~/Saham
# git pull (kalau pakai git)
launchctl kickstart -k gui/$(id -u)/com.shariata.app
```

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.shariata.app.plist
launchctl unload ~/Library/LaunchAgents/com.shariata.caffeinate.plist
launchctl unload ~/Library/LaunchAgents/com.shariata.logrotate.plist
rm ~/Library/LaunchAgents/com.shariata.*.plist
sudo pmset -a sleep 1
```

---

## Catatan Penting untuk Scalping

**1. Data delay yfinance**: yfinance ambil data dari Yahoo Finance dengan delay **15-20 menit**. Untuk **scalping ketat** Anda butuh data real-time dari sekuritas Anda atau IDX feed berbayar. Pipeline ini cocok untuk scalping yang lebih relaks (5-15 menit holding), bukan scalping ketat per detik.

**2. Slippage**: ada selisih harga `signal trigger` ↔ `eksekusi di sekuritas` (biasanya 0.5-1%). Pertimbangkan saat set TP +2% — efektifnya bisa cuma +1%.

**3. Komisi sekuritas**: pulang-pergi (beli + jual) biasanya 0.20-0.40%. Jadi minimum profit harus > 0.5% baru break-even. **TP 2% Anda → net ~1.5%**.

**4. Risk management**: dengan CL -1%, satu trade jelek = -Rp 10.000 dari modal Rp 1jt. Tapi 10 trade jelek berturut-turut = -10%. **Maksimal 3 trade scalping per hari** sangat disarankan; jangan over-trade.
