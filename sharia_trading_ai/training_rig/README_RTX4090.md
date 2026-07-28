# Training Rig — RTX 4090 (kantor, satu LAN dengan NAS)

Peran mesin ini dalam arsitektur tiga simpul:

```
RTX 4090 (pabrik model)  ── latih & evaluasi ──▶  NAS 7TB (datalake pusat)
        ▲                                              │
        └── baca data mentah (LAN, cepat)              ▼  sync harian 17:05 WIB
                                            Mac Mini (produksi 24/7)
                                            validasi → promosi → auto-reload
```

Mac Mini TIDAK pernah bergantung pada rig; rig hanya memasok kandidat model
ke NAS. Validasi & promosi selalu di sisi Mini (`app/ml/model_ingest.py`).

## Setup sekali (Linux/WSL disarankan; Windows native juga bisa)

```bash
git clone https://github.com/hanif7108/Saham.git && cd Saham/sharia_trading_ai
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# GPU (opsional, LightGBM CUDA): pip install lightgbm --config-settings=cmake.define.USE_CUDA=ON
```

Akses NAS (satu LAN — pakai IP lokal NAS, bukan Tailscale, agar cepat):

```bash
ssh-copy-id qnap@<IP-LAN-NAS>        # sekali; selanjutnya tanpa password
export DATALAKE="qnap@<IP-LAN-NAS>:/share/CACHEDEV1_DATA/DataLake/saham-syariah"
```

## Siklus kerja (otomatiskan via cron mingguan di rig bila mau)

```bash
bash training_rig/train_and_publish.sh          # tarik data -> latih -> publikasi kandidat
```

Skrip itu:
1. `rsync` data mentah dari NAS (`raw/prices/` — kini 844 ticker IDX penuh,
   `raw/fundamentals/`, `predictions/` utk riset) ke `ml_data/` lokal rig.
2. Bangun dataset + latih SEMUA varian (classifier h5/h10/h20, screened,
   rank) dengan walk-forward sadar-biaya — di rig boleh eksperimen berat:
   grid hyperparameter, fitur baru, kelak DL (PyTorch + CUDA).
3. Menaruh hasil di NAS `models/candidate/<tanggal>_<nama>/`:
   artifact + meta.json (wajib memuat walkforward_metrics).
4. **Promosi TIDAK otomatis**: sentuh file `PROMOTE` di folder kandidat
   hanya bila metrik walk-forward-nya mengalahkan produksi:
   ```bash
   ssh qnap@<IP-LAN-NAS> "touch '/share/.../models/candidate/<nama>/PROMOTE'"
   ```
5. Mac Mini (job 17:05 WIB) menarik kandidat, memvalidasi (kontrak fitur,
   artifact termuat, ada metrics, ada PROMOTE), backup model lama, pasang —
   dan model baru aktif TANPA restart (auto-reload mtime).

## Aturan main (agar produksi tetap aman)

- Kandidat TANPA `walkforward_metrics` di meta = otomatis ditolak Mini.
- Kandidat dengan `feature_columns` berbeda dari kontrak produksi = ditolak
  (ubah kontrak fitur lewat git, bukan lewat artifact).
- Bandingkan selalu dengan angka SADAR-BIAYA (slippage tick BEI + fee 0.4%;
  lihat README_ML bagian v3) — bukan angka kotor.
- Satu kandidat = satu folder; jangan menimpa folder lama (jejak riset).
