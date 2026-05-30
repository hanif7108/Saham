# Sharia Trading Assistant — Deployment Guide

Tiga jalur deployment yang didukung:

1. **systemd + gunicorn + nginx** (rekomendasi server VPS Linux)
2. **Docker** (paling portable)
3. **Development** (`python3 app.py` — sudah jalan di Mac/lokal)

---

## Opsi 1: Systemd + Gunicorn + Nginx (Linux server)

### Prasyarat
- Ubuntu/Debian server
- Python 3.10+, nginx, certbot (opsional untuk HTTPS)
- Domain (opsional, bisa pakai IP)

### Langkah

```bash
# 1. Clone/copy folder Saham ke server
scp -r ~/Saham hanif@your-server:/home/hanif/

# 2. SSH ke server, buat venv & install deps
ssh hanif@your-server
cd /home/hanif/Saham
python3 -m venv venv
source venv/bin/activate
pip install -r deploy/requirements.txt

# 3. Test gunicorn manual
gunicorn -c deploy/gunicorn_config.py app:app
# Open http://server-ip:8000 untuk verify
# Ctrl+C kalau OK

# 4. Install systemd service
sudo cp deploy/sharia-ta.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sharia-ta
sudo systemctl start sharia-ta
sudo systemctl status sharia-ta   # cek aktif

# 5. Setup nginx reverse proxy
sudo cp deploy/nginx_sharia-ta.conf /etc/nginx/sites-available/sharia-ta
sudo ln -s /etc/nginx/sites-available/sharia-ta /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# 6. (Opsional) HTTPS dengan Let's Encrypt
sudo certbot --nginx -d sharia-ta.example.com
```

### Operasi harian

```bash
# View log
sudo journalctl -u sharia-ta -f
tail -f /home/hanif/Saham/logs/gunicorn_error.log
tail -f /home/hanif/Saham/logs/alerts.log

# Restart
sudo systemctl restart sharia-ta

# Reload tanpa downtime (kalau ganti code)
sudo systemctl reload sharia-ta
```

---

## Opsi 2: Docker

```bash
# Build image
docker build -t sharia-ta -f deploy/Dockerfile .

# Run (mount cache + logs + exports agar persisten)
docker run -d \
  --name sharia-ta \
  -p 8000:8000 \
  -v $(pwd)/cache:/app/cache \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/exports:/app/exports \
  -e SMTP_HOST=smtp.gmail.com \
  -e SMTP_USER=your@gmail.com \
  -e SMTP_PASS=your-app-password \
  -e ALERT_TO=hanif0208@gmail.com \
  sharia-ta

# Logs
docker logs -f sharia-ta

# Stop / restart
docker stop sharia-ta && docker rm sharia-ta
```

---

## Email Alert (Opsional)

Set environment variables sebelum start:

| Variable    | Deskripsi                                      |
|-------------|------------------------------------------------|
| `SMTP_HOST` | mis. `smtp.gmail.com`                          |
| `SMTP_USER` | email pengirim                                 |
| `SMTP_PASS` | app password (Gmail) atau SMTP password        |
| `ALERT_TO`  | email penerima alert (default kosong = no email) |

Email hanya dikirim untuk alert dengan `severity: high` (Strong Buy, Cut Loss, Take Profit) — supaya tidak spam.

---

## Cron job (alternatif scheduler internal)

Kalau lebih suka cron daripada APScheduler internal:

```cron
# /etc/cron.d/sharia-ta
# Rebuild master data tiap pagi 06:00
0 6 * * 1-5 hanif cd /home/hanif/Saham && /home/hanif/Saham/venv/bin/python3 build_master_data.py >> logs/cron.log 2>&1

# Alert scan tiap 30 menit jam pasar (09-15 WIB)
*/30 9-15 * * 1-5 hanif curl -s -X POST http://127.0.0.1:8000/api/alerts/scan >> /home/hanif/Saham/logs/cron-alerts.log 2>&1
```

---

## Folder structure produksi

```
/home/hanif/Saham/
├── app.py
├── modules/         (technical_analysis, scoring, alerts, export, ...)
├── static/, templates/
├── cache/           (auto-managed, persisten)
├── logs/            (gunicorn, alerts, scheduler)
├── exports/         (xlsx, pdf hasil export)
├── deploy/          (config production)
└── venv/            (Python virtualenv)
```

---

## Hardening checklist

- [x] Service jalan sebagai user non-root
- [x] systemd `ProtectSystem=strict`, `PrivateTmp=true`
- [x] nginx block dotfiles
- [x] Static files cache 7 hari
- [ ] HTTPS via certbot (manual, sesuai domain)
- [ ] Firewall: hanya port 80/443 terbuka, blok 8000 dari luar
- [ ] Backup `cache/`, `portfolio.csv`, `master_data_syariah.csv` daily
- [ ] Monitoring uptime (mis. Uptime Kuma)
