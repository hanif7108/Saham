# Sharia Trading AI

Web service **decision-support** untuk trading saham **syariah** di Bursa Efek
Indonesia (BEI), mengimplementasikan metodologi dari _"Sharia Investment and
Trading Module"_ (Doddy Eka Putra / YLive Academy, Platinum Plus) dengan
kepatuhan pada **Fatwa DSN-MUI**.

> ⚠️ **Advisory only.** Aplikasi ini hanya melakukan analisa & memberi sinyal.
> Aplikasi **tidak mengeksekusi order** ke broker. Bukan ajakan jual/beli —
> seluruh keputusan & risiko di tangan pengguna.

## Metodologi — "Stock Funnel"

```
700+ saham BEI
  → 500+ saham Syariah        (screening Fatwa DSN-MUI)   WHAT  to buy
  → CAN SLIM + 6 Magic Number (fundamental)               WHY   to buy
  → Analisa Teknikal           (SMA/Stochastic/breakout)  WHEN  to buy
  → Money Management & Plan     (Taichi/RRR/sizing)        HOW   to trade
```

### 1. Kepatuhan Syariah (`core/sharia_screening.py`)
- Keanggotaan **Daftar Efek Syariah (DES/ISSI)** OJK (otoritatif).
- Re-cek rasio: utang berbasis bunga / aset ≤ 45%, pendapatan non-halal ≤ 10%.
- Transaksi **tunai, long-only** (tanpa margin/riba/short) — Fatwa No. 80/2011.

### 2. 6 Magic Number (`core/fundamental.py`)
EPS(+), ROA>15%, ROE>15%, DER<1, PBV<1, PER<10x; bonus Dividend Yield>7%.

### 3. CAN SLIM (`core/canslim.py`)
C (EPS kuartal YoY>25%), A (EPS tahunan>20% 3thn & ROE>17%), N (dekat ATH),
S (free float <50% + volume/FF ketat), L (rank ≤3 sektor atau RS vs IHSG), I (institutional), M (IHSG vs MA50).

**Satu sumber data dengan 6 Magic Number** via `fundamental.get_metrics()` (hybrid:
TradingView → master_data → yfinance). Funnel selalu memanggil
`evaluate_canslim(..., fund=fund)` agar huruf C tidak bisa `n/a` sementara Magic
sudah terisi (regresi anti-PSAB).

### 4. Teknikal (`core/technical.py`)
SMA200 (filter tren), Stochastic (%K/%D, OB/OS, golden/dead cross), support/resistance,
pola candlestick reversal, deteksi entry: **FBO, 52WBO, BOR, BDTL, Buy-on-Pullback/Dips, Gap Up**.

### 5. Money Management & Trading Plan (`core/trading_plan.py`)
Position sizing (LOT = Modal/MP/100), **Taichi** (OB1/OB2/OB3, konservatif 2:4:8 /
moderat 30:30:40), average, RRR (min 1:2), trading/loss(3%)/profit(6%) fund.

### 6. Scoring rekomendasi (`core/layered_scoring.py`)
Default `SCORING_MODEL=layered` (rollback: `legacy` di `.env`):

1. **Hard gate**: DES/ISSI → spread ≤2% & vol median 5d ≥ Rp5jt → IHSG bukan ekstrem (MA20 < MA60 by >5%).
2. **Quality**: `Fund×0.3 + Tech×0.2 + Bandar×0.15 + Liq×0.15 + IHSG×0.15 + Risk×0.1` (bobot spreadsheet).
3. **Timing** (terpisah, layak entry ≥65) + **Multiplier**: BULLISH ×1 · NEUTRAL ×0.8 · BEARISH ×0 (×0.5 defensif).
4. **Final** = Quality × Mult (+ Timing Bonus 0): ≥75 STRONG BUY · 55–74 WATCHLIST · <55 SKIP.

## Menjalankan

```bash
cd sharia_trading_ai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Buka:
- Dashboard : http://127.0.0.1:8000/
- API docs  : http://127.0.0.1:8000/docs

### Tampilan web
UI **glassmorphism** (gaya selaras app lama "Sharia Trading Assistant v2"): mesh
background, glass panel, font Outfit, gradient logo, **toggle tema light/dark**.
Di `app/templates/index.html` + `app/static/{style.css,app.js}`:
- **Dashboard** — **Pusat Keputusan** (kategorisasi saham → BELI / PANTAU / HINDARI),
  status arah pasar IHSG (vs SMA200), universe syariah, diagram funnel.
- **Analisa Saham** — hero + skor ring, **grafik candlestick interaktif**
  (TradingView lightweight-charts) dengan SMA20/50/200, support/resistance, pane
  Stochastic (OB80/OS20), sinyal entry, kartu 6 Magic Number & grid CAN SLIM.
- **Screening** — tabel ter-ranking (score bar, badge aksi, klik baris → analisa).
- **Trading Plan** — kalkulator Money Management, Taichi, RRR.
- **Pedoman** — ringkasan metodologi & Fatwa (referensi).
- Header: toggle tema, Refresh, **Export CSV** hasil screening.

## Endpoint utama

| Method | Path | Fungsi |
|---|---|---|
| GET | `/api/universe` | daftar saham syariah seed |
| GET | `/api/sharia/{ticker}` | screening syariah 1 saham |
| GET | `/api/analyze/{ticker}` | laporan funnel lengkap |
| GET | `/api/fundamental/{ticker}` | 6 Magic Number |
| GET | `/api/canslim/{ticker}` | skor CAN SLIM |
| GET | `/api/technical/{ticker}` | teknikal & sinyal entry |
| GET | `/api/screen?min_magic=&min_canslim=&require_uptrend=&limit=` | funnel ranking |
| POST | `/api/plan/money-management` | pembagian dana |
| POST | `/api/plan/position-size` | hitung lot |
| POST | `/api/plan/taichi` | Taichi plan |
| POST | `/api/plan/rrr` | risk reward ratio |
| GET | `/api/advisor/status` | cek AI Advisor aktif |
| GET | `/api/advisor/{ticker}` | narasi analisa + saran (Claude) |
| GET/POST/DELETE | `/api/portfolio[/{id}]` | portofolio + P/L live |
| GET | `/api/commodities` | emas, perak, minyak, kurs + Dinar/Dirham |
| GET | `/api/alerts` | pindai peluang entry + status portofolio |
| GET | `/api/telegram/status` | status konfigurasi Telegram |
| POST | `/api/telegram/send` | kirim ringkasan alert ke Telegram |

## Advisor (narasi analisa)

Tombol ✦ Advisor menghasilkan narasi analisa + saran trading plan berbahasa
Indonesia (ringkasan, kekuatan, risiko, teknikal, saran), tetap dalam koridor syariah.
Pilih di dropdown, atau `auto` (**Gemini → DeepSeek → Lokal**):

| Engine | Biaya | Kecepatan | Modul |
|---|---|---|---|
| **Gemini** (`gemini-2.5-flash`) | gratis (free tier, ada kuota/RPM) | ~5–10 dtk | `core/gemini_advisor.py` |
| **DeepSeek** (`deepseek-chat`) | saldo API DeepSeek | ~5–15 dtk | `core/deepseek_advisor.py` |
| **Lokal** (berbasis aturan) | gratis | instan | `core/local_advisor.py` |

- **Gemini** aktif bila `GEMINI_API_KEY` di-set (gratis dari [aistudio.google.com](https://aistudio.google.com/apikey)):
  ```bash
  echo 'GEMINI_API_KEY=AIza...' >> .env   # lalu restart uvicorn
  ```
  Atur model via `GEMINI_MODEL` (default `gemini-2.5-flash`). Pakai REST langsung (httpx),
  tanpa SDK. Free tier punya batas RPM/harian — bila kena limit/overload, app otomatis
  **fallback ke Advisor Lokal**.
- **DeepSeek** aktif bila `DEEPSEEK_API_KEY` di-set ([platform.deepseek.com](https://platform.deepseek.com)):
  ```bash
  echo 'DEEPSEEK_API_KEY=sk-...' >> .env
  # opsional: DEEPSEEK_MODEL=deepseek-chat
  ```
  Lalu restart uvicorn. Pilih **◈ DeepSeek** di dropdown Advisor.
- Paksa engine: `GET /api/advisor/{ticker}?engine=gemini|deepseek|lokal`.

### Prefetch Funnel (jam bursa IDX)
Server menghitung ulang Pusat Keputusan tiap **30 menit** saat jam bursa
(08:45–16:15 WIB, hari perdagangan). Hasil disimpan di cache; membuka web
menampilkan data maksimal 30 menit sebelumnya. Tombol **Jalankan Funnel**
memaksa hitung ulang (`?refresh=true`). Nonaktifkan: `FUNNEL_CACHE_ENABLED=false`.

## Test

```bash
pytest -q
```

## Catatan data
- **Fundamental**: `app/data/master_data_syariah.csv` — data **terkurasi** 75 saham
  DES/ISSI (EPS QnQ, ROA, ROE, NPM, PER, PBV, DER, BVPS, MP, Free Float, Dividend
  Yield; sumber google+yfinance+stockbit) hasil integrasi dari app produksi.
  Jauh lebih akurat untuk saham IDX dibanding yfinance murni (yang sering `n/a`
  untuk EPS kuartal/PBV/free-float). Loader: `app/data/master_data.py`.
- **Harga/teknikal**: **yfinance** (suffix `.JK`) untuk OHLCV historis, chart,
  Stochastic, volume, indeks IHSG.
- CAN SLIM diselaraskan dengan app produksi: C dari EPS QnQ master data, S = volume
  spike ≥1.5x **dan** free float <50%, L = rank ≤3 sektor (by fundamental score),
  I ≥1%, M = IHSG vs MA50.

## Acuan
- Fatwa DSN-MUI No. 40/DSN-MUI/X/2003 — Pasar Modal Syariah.
- Fatwa DSN-MUI No. 80/DSN-MUI/III/2011 — Mekanisme Perdagangan Efek Ekuitas.
- _Sharia Investment and Trading Module_ — Doddy Eka Putra, YLive Academy.
