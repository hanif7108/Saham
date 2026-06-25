# Pindah & Sinkronisasi ke Mac mini (via Thunderbolt)

Tujuan: aplikasi berjalan di **Mac mini** (selalu nyala) sebagai **server tunggal +
sumber data tunggal**, diakses dari **MacBook** lewat browser via **Thunderbolt
Bridge** (super cepat, 10–40 Gbps). Ini cara paling AMAN untuk data trading karena
**hanya ada satu salinan data yang ditulis** → tidak ada konflik/korupsi.

> Prinsip: **kode** disinkron MacBook → Mac mini (Anda develop di MacBook, deploy ke
> Mac mini). **Data** hidup di Mac mini; MacBook melihatnya live via browser, dan
> bisa di-backup ke MacBook kapan saja.

---

## A. Hubungkan via Thunderbolt Bridge (sekali)
1. Sambungkan MacBook ↔ Mac mini dengan **kabel Thunderbolt/USB-4**.
2. Di kedua Mac: **System Settings → Network**. Akan muncul **"Thunderbolt Bridge"**.
   - Biarkan "Using DHCP" (otomatis dapat IP `169.254.x.x`), ATAU set manual:
     Mac mini `10.0.0.2`, MacBook `10.0.0.1`, subnet `255.255.255.0`.
3. Di **Mac mini**: aktifkan SSH → **System Settings → General → Sharing → Remote
   Login: ON** (catat nama, mis. `hanifs-mac-mini.local`).
4. Uji dari MacBook: `ping hanifs-mac-mini.local` lalu `ssh hanif@hanifs-mac-mini.local`.
   - Nama `.local` (Bonjour) otomatis jalan lewat Thunderbolt Bridge.

> (Alternatif transfer awal tanpa SSH: **AirDrop** seluruh folder. Tapi untuk
> sinkronisasi rutin, SSH + rsync jauh lebih praktis.)

---

## B. Pindah pertama kali (sekali)
Di **MacBook**, dari folder aplikasi:
```bash
# sesuaikan dulu nama/user Mac mini
nano deploy/config.sh        # set MACMINI_USER & MACMINI_HOST
chmod +x deploy/*.sh

./deploy/1_initial_transfer.sh   # salin kode + data ke Mac mini (tanpa .venv)
./deploy/2_setup_macmini.sh      # buat venv + install dependensi di Mac mini
./deploy/3_run_on_macmini.sh     # jalankan server (bind 0.0.0.0)
```
Prasyarat di Mac mini: **Python 3** & **Tesseract** (`brew install tesseract`) untuk OCR.

## Akses Dashboard
Kunjungi alamat server Mac Mini Anda melalui browser MacBook untuk menggunakan seluruh fitur di atas (menggunakan koneksi tercepat):
👉 **[http://192.168.1.115](http://192.168.1.115)** (Koneksi LAN Tercepat)
👉 **[http://100.107.4.14](http://100.107.4.14)** (Koneksi VPN Tailscale)

---

## C. Pemakaian harian (sinkron)
- **Selalu akses lewat browser ke Mac mini** → Anda & Mac mini melihat **data yang
  sama persis** (satu sumber). Tidak perlu sinkron data manual.
- **Ubah program?** Edit di MacBook lalu:
  ```bash
  ./deploy/deploy_code.sh      # kirim kode ke Mac mini + restart (data utuh)
  ```
- **Backup data ke MacBook** (mis. sebelum perubahan besar / arsip):
  ```bash
  ./deploy/backup_data.sh      # tarik data_store dari Mac mini → MacBook + arsip timestamp
  ```
- **Akses dari luar rumah** (opsional): pakai **Tailscale** (seperti app lama Anda),
  nama jadi `hanifs-mac-mini.tail....ts.net`.

---

## D. Mau benar-benar BIDIREKSIONAL (jalan di kedua Mac)?
Hanya bila Anda butuh menjalankan aplikasi **di MacBook saat Mac mini mati** (mis.
bepergian). Gunakan **Syncthing** (sinkron folder dua arah, otomatis saat satu
jaringan, tanpa cloud):

```bash
brew install syncthing           # di KEDUA Mac
brew services start syncthing    # buka http://127.0.0.1:8384
```
1. Di kedua Mac, tambah folder `~/Saham/sharia_trading_ai` (Folder ID sama).
2. Hubungkan kedua device (scan Device ID via Thunderbolt/LAN).
3. Syncthing akan menjaga **kode + data_store** identik otomatis saat keduanya nyala.

> ⚠️ **WAJIB** bila pakai mode ini: **jangan jalankan server di KEDUA Mac
> bersamaan** — keduanya menulis ke `data_store/*.json` → bisa konflik/korup.
> Jalankan di SATU Mac saja pada satu waktu; biarkan Syncthing menyamakan data
> sebelum berpindah komputer. Exclude `.venv/`, `__pycache__/`, `.ocrtmp/`,
> `deploy/backups/` di Syncthing (mesin-spesifik).

---

## Ringkasan rekomendasi
| Kebutuhan | Solusi |
|-----------|--------|
| **Disarankan** — aman, tanpa konflik | Mac mini = server tunggal; MacBook akses via browser; `deploy_code.sh` utk update kode; `backup_data.sh` utk cadangan |
| Harus jalan di kedua Mac (offline-able) | Syncthing dua-arah + **jangan jalankan server bersamaan** |

Data yang disinkron/di-backup: seluruh `data_store/` — `portfolio.json`,
`accounts.json`, `trades.json` (jurnal ROI), `dividend_calendar.json`,
`bei_holidays.json`, dan `app/data/master_data_syariah.csv`.
