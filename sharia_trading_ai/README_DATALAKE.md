# Datalake Trading Saham Sharia — NAS via Tailscale

Arsip data lengkap (basis training AI) di NAS Synology `100.70.97.42`,
sementara Mac Mini hanya menyimpan data panas yang dibutuhkan runtime.

## Prinsip desain (Mac Mini & NAS beda lokasi)

- **Aplikasi tidak pernah menyentuh NAS saat runtime.** Latensi Tailscale
  antar-lokasi 300–1000ms; mount langsung (SMB/NFS) bisa menggantung proses
  24/7 saat link putus. Semua baca-tulis runtime tetap lokal.
- **Sync harian satu arah (push) via rsync over SSH**, 17:05 WIB, setelah
  pencatatan track record 16:20. Incremental, resume-safe (`--partial`),
  timeout ketat; NAS offline = dilewati dengan log rapi, data menunggu lokal.
- **Append-only di NAS**: snapshot harian tidak pernah ditimpa — inilah nilai
  datalake untuk training (point-in-time, bebas survivorship/look-ahead bias).
- **Pruning lokal**: snapshot lokal > 14 hari dihapus HANYA setelah sukses
  tersalin ke NAS — storage Mac Mini tetap ramping.

## Struktur di NAS (`/volume1/DataLake/saham-syariah/`)

```
raw/
  prices/            # OHLCV penuh per ticker (parquet, mirror ml_data/history)
  fundamentals/      # master_data_syariah_YYYY-MM-DD.csv — snapshot HARIAN
                     #   -> kelak jadi data fundamental point-in-time utk fitur ML!
curated/
  datasets/          # dataset_latest.parquet (feature matrix + label)
  walkforward/       # prediksi & metrik walk-forward per horizon
predictions/
  ml_track.parquet   # track record prediksi-vs-realisasi (append harian)
  ml_track_summary.json
  decisions/         # decisions_YYYY-MM-DD.json — keputusan lengkap app per hari
models/
  YYYY-MM/           # artifact LightGBM + meta per retrain bulanan (berversi)
logs/                # audit data dsb.
```

## Aktivasi — SATU langkah manual (sekali saja)

Sync butuh SSH key (tanpa password, aman untuk otomasi). Dari terminal
Mac Mini, jalankan dan masukkan password NAS **sekali**:

```bash
ssh-copy-id hanif@100.70.97.42
```

> Bila ditolak: di DSM aktifkan dulu **Control Panel → User & Group →
> Advanced → Enable user home service**, dan pastikan SSH aktif
> (**Terminal & SNMP → Enable SSH service**). Folder `DataLake` dibuat
> otomatis oleh script pada sync pertama (buat shared folder `DataLake`
> di DSM bila belum ada).

Uji langsung:

```bash
bash /Users/hanif/Saham/sharia_trading_ai/scripts/datalake_sync.sh
```

## Operasional

- Jadwal: `com.shariata.datalake_sync` (LaunchAgent) harian **17:05 WIB**.
- Status: `GET /api/datalake/status` + chip 🗄️ di panel Track Record dashboard.
- Log: `logs/datalake_sync.log` · state: `ml_data/datalake_state.json`.
- Restore (disaster recovery / Mac Mini baru):
  `bash scripts/datalake_sync.sh pull`
- Override host/user/path via env: `DATALAKE_HOST`, `DATALAKE_USER`,
  `DATALAKE_REMOTE`.
