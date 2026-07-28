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

## Audit data (2026-07-28)

- 76 ticker (75 syariah + ^JKSE), median histori 20.8 tahun. Dataset training
  mulai 2015 (era sebelumnya banyak split tak tercatat di Yahoo).
- WSKT: hanya 1 bar (suspensi) → dikecualikan (`EXCLUDE` di dataset.py).
- Anomali split tak tercatat (MAPI Mei-2018, INKP Jun-2019, FILM Agu-2018):
  sampel yang jendela forward-nya memuat |ret harian| > 30% dibuang otomatis.
- IPO muda (AMMN, PGEO, GOTO, ADMR, MTEL): ikut selama punya ≥ 300 bar.
