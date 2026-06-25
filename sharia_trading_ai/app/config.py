"""
Konfigurasi & ambang batas (threshold) aplikasi.

Seluruh angka di sini diambil LANGSUNG dari "Sharia Investment and Trading
Module" (Doddy Eka Putra / YLive Academy, Platinum Plus 2025) dan dari kriteria
screening syariah OJK / Fatwa DSN-MUI. Mengubah strategi cukup di file ini.
"""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR.parent / "data_cache"
TEMPLATES_DIR = BASE_DIR / "templates"


# --------------------------------------------------------------------------- #
#  6 MAGIC NUMBER — Analisa Fundamental (modul hal. 12)                        #
# --------------------------------------------------------------------------- #
class FundamentalThresholds:
    EPS_MIN = 0.0          # EPS wajib positif (+)
    ROA_MIN = 15.0         # ROA > 15%
    ROE_MIN = 15.0         # ROE > 15%
    DER_MAX = 1.0          # DER < 100% (<1)
    PBV_MAX = 1.0          # PBV < 1  (BVPS > Market Price = undervalue)
    PER_MAX = 10.0         # PER < 10x
    DIVIDEND_YIELD_MIN = 7.0  # Bonus: Dividend Yield > 7%


# --------------------------------------------------------------------------- #
#  CAN SLIM — Strategi Tekno-Fundamental (modul hal. 15-20)                    #
# --------------------------------------------------------------------------- #
class CanslimThresholds:
    # Diselaraskan dengan app lama (Mac Mini) agar rekomendasi konsisten.
    C_QUARTERLY_EPS_GROWTH_MIN = 25.0   # C: EPS QnQ >= 25% (dari master data)
    A_ANNUAL_EPS_GROWTH_MIN = 20.0      # A: annual EPS growth 3thn >= 20%
    A_ROE_MIN = 17.0
    A_YEARS = 3

    N_NEAR_HIGH_PCT = 85.0             # N: harga >= 85% dari 52W high

    # S — Supply & Demand: volume spike >= 1.5x DAN free float < 50% (KEDUANYA)
    S_VOLUME_SPIKE_MULT = 1.5
    S_FREE_FLOAT_MAX_PCT = 50.0
    CAP_SMALL_MAX_T = 1.0
    CAP_BIG_MIN_T = 50.0

    L_TOP_RANK = 3                     # L: rank <= 3 di sektor (by fundamental score)

    I_INSTITUTION_MIN_PCT = 1.0        # I: institusi >= 1%

    M_MA_PERIOD = 50                   # M: IHSG vs MA50 (uptrend)


# --------------------------------------------------------------------------- #
#  ANALISA TEKNIKAL (modul hal. 30-50)                                        #
# --------------------------------------------------------------------------- #
class TechnicalParams:
    SMA_TREND_PERIOD = 200             # SMA 200 sebagai filter tren utama
    SMA_FAST = 20
    SMA_SLOW = 50

    STOCH_RSI_PERIOD = 14              # Stochastic RSI period (umum 14 hari)
    STOCH_K_SMOOTH = 3                 # %K smoothing (MA 3)
    STOCH_D_SMOOTH = 3                 # %D = MA dari %K
    STOCH_OVERBOUGHT = 80.0            # OB > 80
    STOCH_OVERSOLD = 20.0              # OS < 20

    SR_LOOKBACK = 60                   # cari support/resistance dari N candle
    SR_PIVOT_WINDOW = 5                # swing high/low window
    SR_MAX_LEVELS = 6                  # jumlah zona S/R yang ditampilkan (terkuat)
    SR_CLUSTER_TOL_PCT = 1.5          # pivot berjarak < tol% digabung jadi 1 zona

    BREAKOUT_LOOKBACK_52W = 252        # ~ 52 minggu trading
    VOLUME_AVG_PERIOD = 20             # rata-rata volume 20 hari
    VOLUME_SPIKE_MULT = 1.5            # lonjakan volume


# --------------------------------------------------------------------------- #
#  MONEY MANAGEMENT & TRADING PLAN (modul hal. 51-56)                         #
# --------------------------------------------------------------------------- #
class MoneyManagement:
    TRADING_FUND_PCT = 50.0            # Trading fund = 50% dari idle money
    LOSS_FUND_PCT = 3.0               # Risk default = 3% (Loss fund = bid fund x risk%)
    PROFIT_FUND_PCT = 6.0            # Target profit default = 6% (Profit fund = bid fund x profit%)
    RISK_MAX_PCT = 5.0              # Risk maksimal 5% (aturan MM TP)
    PROFIT_MIN_RISK_MULT = 2        # Target profit minimal 2x risk
    SHARES_PER_LOT = 100             # 1 LOT = 100 lembar (BEI)

    # Biaya transaksi default (%) — bisa di-set berbeda per RDN/broker.
    # Beli ~0.15% (komisi+PPN), Jual ~0.25% (komisi+PPN+levy+PPh final 0.1%).
    FEE_BUY_PCT = 0.15
    FEE_SELL_PCT = 0.25

    # Taichi Trading Plan — rasio alokasi OB1:OB2:OB3
    TAICHI_KONSERVATIF = (2, 4, 8)    # dibagi total 14
    TAICHI_MODERAT = (30, 30, 40)    # persen
    DEFAULT_RRR = (1, 2)             # Risk : Reward minimal 1:2


# --------------------------------------------------------------------------- #
#  KEPATUHAN SYARIAH — Fatwa DSN-MUI (screening OJK / DES)                     #
# --------------------------------------------------------------------------- #
class ShariaScreening:
    """
    Acuan:
      - Fatwa DSN-MUI No. 40/DSN-MUI/X/2003 (Pasar Modal Syariah)
      - Fatwa DSN-MUI No. 80/DSN-MUI/III/2011 (mekanisme perdagangan ekuitas)
      - Kriteria rasio keuangan Daftar Efek Syariah (OJK).
    """
    # Rasio total utang berbasis bunga / total aset <= 45%
    INTEREST_DEBT_TO_ASSET_MAX_PCT = 45.0
    # Rasio total pendapatan non-halal (bunga + lain) / total pendapatan <= 10%
    NON_HALAL_INCOME_TO_REVENUE_MAX_PCT = 10.0

    # Praktik perdagangan yang DILARANG menurut Fatwa No. 80 (long-only, tunai).
    PROHIBITED_PRACTICES = [
        "Margin trading (mengandung riba)",
        "Short selling / bai' al-ma'dum (jual barang yang belum dimiliki)",
        "Najsy (penawaran palsu untuk menggiring harga)",
        "Ghisysy / tadlis (menyembunyikan cacat informasi)",
        "Insider trading & front running",
        "Wash sale / pooling interest / cornering / pump and dump",
        "Ihtikar (menimbun untuk menggerakkan harga)",
    ]


class Settings(BaseSettings):
    # baca .env app ini (absolut, bebas-cwd), lalu .env workspace lama (Telegram)
    model_config = SettingsConfigDict(
        env_file=(str(BASE_DIR.parent / ".env"), str(BASE_DIR.parent.parent / ".env")),
        extra="ignore",
    )

    app_name: str = "Sharia Trading AI"
    cache_ttl_seconds: int = 60 * 10       # 10 menit (cukup segar utk pemantau intraday)
    price_ttl_seconds: int = 60 * 3        # 3 menit — harga posisi/jual lebih live (intraday 5m)
    trading_mode: str = "swing"            # swing | scalping

    # Sumber fundamental untuk screening (6 Magic Number / CAN SLIM):
    #   "hybrid"      = TradingView live dulu, fallback master_data lalu yfinance (DEFAULT)
    #   "tradingview" = scanner TradingView live saja (+ fallback master/yfinance)
    #   "master_data" = CSV terkurasi (perilaku lama; pilih ini utk kembali ke semula)
    #   "yfinance"    = yfinance saja
    # Override tanpa edit kode: set DATA_SOURCE=master_data di .env. Funnel tetap
    # berjalan walau TradingView gagal (graceful fallback).
    data_source: str = "hybrid"
    tradingview_screener: str = "indonesia"   # scanner region TradingView (BEI)
    tradingview_exchange: str = "IDX"
    tradingview_ttl_seconds: int = 60 * 10    # cache scan fundamental (detik)

    # opsional — AI advisor (Claude). Kosong = fitur AI dinonaktifkan.
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-4-8"

    # opsional — Gemini (Google AI Studio, ada free tier). Kosong = nonaktif.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # opsional — Telegram notifikasi
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False

    # opsional — Bandarmologi & Smart Money
    bandarmologi_provider: str = "volatility_proxy"
    bandarmologi_api_url: str = ""
    bandarmologi_api_key: str = ""

    # Ollama (LLM lokal gratis) — auto-detect bila server jalan
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:latest"

    # Rebuild master_data terjadwal (jam). 0 = nonaktif (rebuild manual saja).
    master_rebuild_hours: int = 24

    # Pengingat harian via Telegram (waktu server-lokal, set mesin ke WIB).
    # Pagi: siapkan order sebelum buka · Sore: jalankan funnel & review.
    reminder_enabled: bool = True
    reminder_morning: str = "08:00"      # sebelum bursa buka (09:00)
    reminder_evening: str = "17:00"      # sesudah bursa tutup (16:00)

    # Pemantau Funnel intraday: tiap N menit (jam bursa) jalankan funnel & kirim
    # Telegram HANYA bila ada sinyal BARU & signifikan (eksit mendesak / BELI kuat).
    funnel_watch_enabled: bool = True
    funnel_watch_minutes: int = 15
    funnel_watch_min_conviction: float = 58.0   # ambang skor keyakinan utk alert BELI
    trailing_stop_pct: float = 3.0              # toleransi penurunan trailing stop (%)

    # Mode Uji: paksa sistem berlaku seperti bursa BUKA (sinyal penuh) walau libur.
    # Berguna saat pengembangan agar aliran data/sinyal terus jalan. Default mati.
    force_market_open: bool = False

    # Simulasi Eksekusi Harian (paper trading): rekam kartu BUY Pusat Keputusan
    # tiap pagi hari bursa & evaluasi TP/SL/horizon tiap sore — bahan learning.
    simulation_enabled: bool = True
    simulation_capture_time: str = "09:30"    # rekam rekomendasi (bursa sudah buka)
    simulation_evaluate_time: str = "16:15"   # evaluasi setelah bursa tutup

    # Strategi portofolio mingguan terkonsentrasi: jumlah emiten yang dijaga.
    target_holdings: int = 3
    # Selisih skor kekuatan minimal agar ROTASI (swap) disarankan saat slot penuh.
    rotation_margin: float = 4.0


settings = Settings()

# instans threshold (dipakai modul lain)
FUND = FundamentalThresholds()
CANSLIM = CanslimThresholds()
TECH = TechnicalParams()
MM = MoneyManagement()
SHARIA = ShariaScreening()
