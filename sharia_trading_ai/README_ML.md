# Sinyal ML — LightGBM di atas Pipeline Rule-Based

Evolusi sinyal BUY/SELL/HOLD dari scoring rule-based (CAN SLIM + 6 Magic
Numbers + jalur_7) menjadi model ML terukur (backtestable). Filter syariah
(`sharia_screening`) **tetap rule-based** — keputusan compliance biner tidak
diserahkan ke model probabilistik. LLM (Claude advisor) hanya lapisan
penjelasan di atasnya: menerima `sinyal_ml` + `top_features` dan dilarang
mengarang angka.

## Arsitektur

```
yfinance (max history, auto_adjust=False)          app/ml/data_fetch.py
        │  parquet per ticker → ml_data/history/
        ▼
feature matrix + label forward-return               app/ml/features.py
  (fitur dari Close mentah = identik runtime;       app/ml/dataset.py
   label dari Adj Close = total return;
   anomali |ret|>30% di-mask; turnover < Rp1M/hari dibuang)
        ▼
walk-forward train/eval per kuartal                 app/ml/train.py
  (purge gap = horizon; test 2024→2026;
   metrik: Sharpe/maxDD/hit-rate + benchmark IHSG & rule-proxy)
        ▼
artifact app/ml/artifacts/ml_signal_h{5,10,20}.txt + meta.json
        ▼
runtime predict + confidence gating                 app/core/ml_signal.py
  (dipanggil funnel.analyze_stock → build_ranking → build_decisions;
   fallback aman: artifact hilang / data kurang → rule-based murni)
```

## Hasil walk-forward (test 2024-01 → 2026-07, biaya 0.4%/roundtrip, top-5)

| Horizon | Sharpe | Total return | Max DD | Hit rate | Rule-proxy | IHSG |
|--------:|-------:|-------------:|-------:|---------:|-----------:|-----:|
| **5 hari**  | **1.10** | **+172%** | −40% | 48.7% | −9.6% | −14.9% |
| 10 hari | 0.68 | +70%  | −51% | 49.9% | +5.1%  | −17.6% |
| 20 hari | 0.40 | +25%  | −34% | 47.8% | −15.0% | −20.5% |

Horizon default production: **5 hari** (`ml_horizon=5`). Angka lengkap per
kuartal: `ml_data/walkforward/metrics_h*.json`.

> Catatan jujur: fitur fundamental (CAN SLIM/Magic) TIDAK ikut dilatih karena
> tidak ada snapshot fundamental historis point-in-time — memakainya akan
> menciptakan look-ahead bias. Gerbang fundamental & syariah tetap rule-based
> di lapisan keputusan. Universe 75 ticker adalah kurasi hari ini
> (survivorship bias ringan pada backtest — dicatat, diterima untuk v1).

## Mode operasi (`.env` → `ML_SIGNAL_MODE`)

- `off`    — modul tidak dipanggil.
- `shadow` — **default.** Prediksi tampil di dashboard (badge 🤖 di Top-5,
  kolom ML di ekspor markdown, `ml_signal` di API /api/decisions) tapi TIDAK
  mengubah keputusan. Bangun track record dulu.
- `active` — bila model confident (P ≥ ambang, default 0.45 dari meta):
  SELL confident = veto entry baru; BUY confident = kandidat BUY
  (context `ML_SIGNAL`, tetap lewat gerbang fundamental minimal & bandarmologi).
  Selain itu: fallback rule-based.

Ambang bisa dioverride: `ML_CONF_THRESHOLD=0.5`. Rekomendasi: naikkan ke
`active` hanya setelah shadow mode berjalan ≥ 1-2 bulan dan track record
simulasi mendukung.

## Perintah

```bash
cd /Users/hanif/Saham/sharia_trading_ai
PYTHONPATH=. .venv/bin/python -m app.ml.data_fetch --audit   # fetch + audit data
PYTHONPATH=. .venv/bin/python -m app.ml.dataset              # rakit dataset
PYTHONPATH=. .venv/bin/python -m app.ml.train                # walk-forward + artifact
PYTHONPATH=. .venv/bin/python -m app.ml.train --no-eval      # artifact saja (cepat)
```

## Deploy di Mac Mini

1. `git pull` di `/Users/hanif/Saham`.
2. `brew install libomp` (sekali saja — dependensi LightGBM).
3. `.venv/bin/pip install -r sharia_trading_ai/requirements.txt`
4. Artifact h5 ikut di git; h10/h20 opsional via retrain. Untuk retrain penuh
   pertama: `bash sharia_trading_ai/scripts/retrain_ml.sh` (≈10 menit).
5. Pasang retrain bulanan (tanggal 1, 05:00 WIB):
   ```bash
   cp sharia_trading_ai/deploy/com.shariata.ml_retrain.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.shariata.ml_retrain.plist
   ```
6. Restart service agar artifact dimuat (uvicorn cache model di memori):
   `launchctl kickstart -k gui/$(id -u)/com.shariata.app`
   (atau label `com.sharia.trading` sesuai plist yang aktif).

## v3 — BACA INI DULU: backtest sadar-biaya (2026-07-28 sore)

Setelah slippage dimodelkan (2 tick BEI per round-trip + fee 0.4%) dan
filter harga >= Rp200 diterapkan point-in-time di dataset, SEMUA angka
indah di bawah bagian ini terbukti ilusi biaya:

| Konfigurasi (test 2024-2026) | Sharpe | Return | Max DD |
|---|---:|---:|---:|
| IHSG | −0.29 | −17.6% | −42% |
| h5 classifier (tanpa biaya realistis: +172%!) | −0.28 | **−41%** | −50% |
| h5 ensemble+veto (tanpa biaya: +224%!) | −0.38 | −39% | −52% |
| h20 classifier | −0.19 | −26% | −39% |
| **h10 classifier + pick harga >= Rp500 (PRODUKSI)** | **+0.53** | **+39.3%** | −39% |

Pelajaran: turnover mingguan × tick size IDX = drag 30-45%/tahun; edge
mentah model tidak cukup menutupnya. Konfigurasi produksi sekarang:
`ml_horizon=10`, kandidat BUY harga >= Rp500 (`ML_MIN_PRICE`), urutan
p_buy classifier (ensemble tampil sebagai info; urutannya TIDAK terbukti
lebih baik setelah biaya). Ekspektasi live yang wajar: Sharpe ~0.3-0.5,
bukan angka fantastis bagian historis di bawah.

Bagian-bagian di bawah dipertahankan sebagai jejak riset (angka PRA-biaya
— jangan dikutip sebagai ekspektasi).

## v4 — Eksperimen multi-seed di rig RTX 4090 (2026-07-28 malam): edge h10 TIDAK terbedakan dari nol

10 model identik-statistik (beda seed saja), walk-forward sadar-biaya h10+p500:

| | ret | Sharpe | IC | IC_IR |
|---|---:|---:|---:|---:|
| Seed terburuk | −48.9% | −0.43 | 0.013 | 0.07 |
| **Median 10 seed** | **−1.5%** | **0.23** | 0.017 | 0.09 |
| Seed terbaik | +92.3% | +0.76 | 0.023 | 0.12 |
| Ensemble rata-rata 10 seed | −17.2% | 0.03 | 0.018 | 0.09 |

Kesimpulan jujur:
1. **Ensemble multi-seed GAGAL uji stabilitas** (di bawah median; IC tidak
   naik) — TIDAK diadopsi ke produksi.
2. **Sinyal h10 terlalu lemah** (IC ~0.017, IR ~0.09; layak-trade umumnya
   butuh IR ≥ 0.3). Dengan sinyal selemah ini, urutan top-5 ≈ undian —
   itulah sumber sebaran −49%..+92% antar model kembar.
3. Angka "+39% / Sharpe 0.53" produksi = **satu undian yang menguntungkan**,
   bukan ekspektasi. Ekspektasi jujur strategi ML saat ini: **≈ 0 ± lebar**
   setelah biaya. (Bandingkan: rank-model h5 ber-IC 0.046/IR 0.31 — 3× lebih
   kuat — arah riset yang lebih menjanjikan daripada tuning seleksi.)
4. Implikasi operasional: mode **shadow dipertahankan tanpa batas waktu**
   sampai track record live ATAU model baru menunjukkan IC_IR ≥ 0.3
   walk-forward. Keputusan shadow→active kini punya ambang kuantitatif.
5. Arah perbaikan bermakna (bukan tuning): fitur fundamental point-in-time
   (datalake sedang menabung), fitur cross-sectional dari universe 844,
   model ranking sebagai mesin utama, horizon/holding lebih panjang.

## Algoritma v2: ensemble ranking lintas-saham + classifier (2026-07-28)

Classifier menjawab "apakah saham X naik >2%?", padahal keputusan trading
sebenarnya "5 terbaik dari kandidat hari ini yang mana?" — itu masalah
peringkat lintas-saham. Maka ditambah **model ranking** (`ml_rank_h5`):
LightGBM regresi persentil forward-return 5d suatu saham RELATIF terhadap
saham lain di tanggal sama, dengan 8 fitur persentil lintas-saham tambahan
(csr_*). Urutan pilihan akhir = **skor ensemble** (rata-rata persentil skor
ranking & p_buy classifier) dengan **veto**: kandidat dibuang bila
P(SELL) classifier ≥ 0.45.

Walk-forward 2024-2026 (top-5, biaya 0.4%):

| Strategi | Sharpe | Return | Max DD |
|---|---:|---:|---:|
| Classifier saja (v1) | 1.10 | +172% | −40% |
| Ranking saja | 1.22 | +164% | −41% |
| **Ensemble + veto SELL (v2)** | **1.46** | **+224%** | **−37%** |

Rank IC 0.046 (IR 0.31). Runtime: skor dihitung batch di `scan_universe`
(persentil antar ticker hari itu), tampil sebagai kolom **Ens⚡** + tanda 🚫
(veto) di dashboard & fokus; Telegram memakai urutan ensemble; tracker
mencatat `rank_score`/`ens_score`/`veto_sell` untuk evaluasi realisasi.
Retrain bulanan melatih ketiga artifact (global, screened, rank).

## Alur dua tahap: screening konvensional → ML (fokus Top-10)

Mekanisme (sesuai keputusan 2026-07-28): **screening konvensional dulu, AI
kemudian** — meningkatkan presisi per sinyal dan menjaga disiplin metoda.

1. **Tahap 1 — screening konvensional**: 6 Magic Numbers + CAN SLIM +
   teknikal + jalur7 (skor funnel layered) memilih **10 saham paling
   prospektif** hari itu.
2. **Tahap 2 — ML menilai hasil screening**: artifact varian
   `ml_signal_h5_screened` (dilatih HANYA pada populasi yang lolos emulasi
   screening historis — `apply_conventional_screen` di dataset.py: uptrend
   SMA200 & SMA50>SMA200, RSI<75, likuid, top-10 skor konvensional per hari,
   26.6rb sampel) memberi P(BUY)/P(SELL) tiap kandidat.

Walk-forward 2024–2026 di populasi screening: model screened Sharpe 0.76 /
+76% / maxDD −45% vs model global di populasi sama 0.61 / +64% / −55%,
dan screening murni tanpa ML hanya +3.8% — dua tahap mengalahkan
masing-masing tahap sendirian. (Panel universe tetap memakai model global
sebagai radar discovery.)

Runtime: `GET /api/ml/focus` + tabel "🎯 Fokus Dua Tahap" di dashboard
(kolom Kesepakatan menandai rule × ML selaras/beda). Track record mencatat
flag `in_focus` sehingga realisasi subset fokus terukur terpisah
(`focus_top10_all`, `focus_top10_ml_buy` di /api/ml/track). Retrain bulanan
melatih ulang kedua varian.

## Lingkaran belajar: prediksi vs realisasi (`app/ml/tracker.py`)

Setiap sore hari bursa (default 16:20, `ML_TRACK_TIME`) sistem otomatis:

1. **Mencatat** prediksi ML (p_buy/p_hold/p_sell, confident) + sinyal rule-based
   seluruh ticker ke `ml_data/ml_track.parquet` (idempoten per tanggal).
2. **Mengevaluasi** prediksi yang horizonnya sudah lewat terhadap harga
   penutupan aktual: outcome (naik/turun/datar per ambang label), benar/salah,
   return realisasi.
3. **Melaporkan** track record via `GET /api/ml/track` + panel
   "🤖 Track Record Sinyal ML" di dashboard: ML BUY confident vs ML BUY semua
   vs rule-based BUY-ish vs baseline universe, plus kalibrasi P(BUY).
4. **Mengkalibrasi ambang confidence** dari realisasi (≥30 sampel BUY
   terevaluasi, grid 0.35–0.60, maksimalkan avg return). Ambang terkalibrasi
   otomatis dipakai `ml_signal.predict()` bila `ML_CONF_THRESHOLD` tidak
   di-set manual (`conf_source` di API menunjukkan sumbernya).

Retrain bulanan ikut menjalankan evaluasi + laporan (lihat
`scripts/retrain_ml.sh`), dan retrain itu sendiri melatih ulang model dengan
data terbaru — realisasi pasar bulan berjalan otomatis menjadi label training
berikutnya. LLM advisor menerima `track_record_ml` agar bobot kepercayaannya
pada sinyal ML ikut realitas, bukan asumsi.

CLI manual:

```bash
PYTHONPATH=. .venv/bin/python -m app.ml.tracker --log        # catat hari ini
PYTHONPATH=. .venv/bin/python -m app.ml.tracker --evaluate   # nilai yg jatuh tempo
PYTHONPATH=. .venv/bin/python -m app.ml.tracker --report     # track record
```

## Audit data (2026-07-28)

- 76 ticker (75 syariah + ^JKSE), median histori 20.8 tahun. Dataset training
  mulai 2015 (era sebelumnya banyak split tak tercatat di Yahoo).
- WSKT: hanya 1 bar (suspensi) → dikecualikan (`EXCLUDE` di dataset.py).
- Anomali split tak tercatat (MAPI Mei-2018, INKP Jun-2019, FILM Agu-2018):
  sampel yang jendela forward-nya memuat |ret harian| > 30% dibuang otomatis.
- IPO muda (AMMN, PGEO, GOTO, ADMR, MTEL): ikut selama punya ≥ 300 bar.
