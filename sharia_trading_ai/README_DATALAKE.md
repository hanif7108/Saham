# Datalake Trading Saham Sharia — NAS via Tailscale

Arsip data lengkap (basis training AI) di NAS QNAP `100.70.97.42` (volume CACHEDEV1_DATA, 7TB),
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

## Struktur di NAS (`/share/CACHEDEV1_DATA/DataLake/saham-syariah/`)

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
  candidate/         # kandidat dari rig RTX 4090 (+PROMOTE/PROMOTED_AT)
research/
  rig_experiments/   # output eksperimen rig per tanggal (multi-seed,
                     #   walk-forward preds) — jejak riset permanen
logs/                # audit data dsb.
```

## Aktivasi — SATU langkah manual (sekali saja)

Sync butuh SSH key (tanpa password, aman untuk otomasi). Dari terminal
Mac Mini, jalankan dan masukkan password NAS **sekali**:

```bash
ssh-copy-id qnap@100.70.97.42
```

> Sudah dilakukan 2026-07-28 (user `qnap`). Folder DataLake dibuat
> otomatis oleh script pada sync pertama.

Uji langsung:

```bash
bash /Users/hanif/Saham/sharia_trading_ai/scripts/datalake_sync.sh
```

## Arsitektur tiga simpul (sejak 2026-07-28 malam)

```
RTX 4090 (kantor)  ── latih & evaluasi ──▶  NAS 7TB (datalake pusat)
       ▲                                          │
       └── baca raw/ via LAN                      ▼  sync harian 17:05 WIB
                                     Mac Mini (produksi 24/7)
                                     collect → push → ingest kandidat model
```

- **Universe penuh IDX (~844 ticker)** dikoleksi harian (`app/ml/universe_collector.py`,
  sumber scanner TradingView, fallback CSV lokal): snapshot keanggotaan ke
  `raw/universe/` (obat survivorship bias ke depan) + OHLCV penuh ke
  `raw/prices/`. Universe TRADING tetap 75 terkurasi.
- **Jalur balik model** (`app/ml/model_ingest.py`): rig menaruh kandidat di
  `models/candidate/<nama>/` (artifact + meta ber-walkforward_metrics +
  marker `PROMOTE`); Mini memvalidasi (kontrak fitur, artifact termuat,
  metrik ada) → backup → pasang → aktif tanpa restart. Tanpa marker/gagal
  validasi = produksi tidak tersentuh.
- **Kit rig**: `training_rig/README_RTX4090.md` + `train_and_publish.sh`.

## Kepemilikan zona (sejak 2026-07-28 malam — WAJIB dipatuhi agar tak saling timpa)

| Zona | Pemilik (penulis) | Kapan |
|---|---|---|
| `raw/prices`, `raw/universe` | **RIG RTX 4090** (broadband kantor, LAN→NAS) | timer 17:20 WIB |
| `raw/fundamentals`, `curated/`, `predictions/`, `models/YYYY-MM`, `logs/audit*` | **Mac Mini** | 17:05 WIB |
| `models/candidate/`, `research/rig_experiments/` | **RIG** | saat training |
| `logs/collect_state.json` | RIG | tiap koleksi |

Pembagian peran: **Mini = web service & keputusan** (internet rumahan cukup —
trafiknya ringan: kuota live 75 ticker + Telegram); **RIG = mesin produksi
data & komputasi** (outbound-only, tanpa port listening — jejak jaringan
kantor minimal). Mini bisa `pull` history dari NAS kapan pun untuk retrain
lokal/restore.

## Operasional

- Jadwal: `com.shariata.datalake_sync` (LaunchAgent) harian **17:05 WIB**.
- Status: `GET /api/datalake/status` + chip 🗄️ di panel Track Record dashboard.
- Log: `logs/datalake_sync.log` · state: `ml_data/datalake_state.json`.
- Restore (disaster recovery / Mac Mini baru):
  `bash scripts/datalake_sync.sh pull`
- Override host/user/path via env: `DATALAKE_HOST`, `DATALAKE_USER`,
  `DATALAKE_REMOTE`.
