"""
Sharia Trading Assistant - Flask App v2
=======================================
Pipeline: O'Neil CAN SLIM + 6 Magic Numbers + Technical Signals.

Endpoints:
  GET  /                   - Dashboard
  GET  /api/portfolio      - Portfolio + sinyal
  POST /api/portfolio      - Tambah/update saham di portfolio
  DEL  /api/portfolio/<t>  - Hapus saham
  GET  /api/prospects      - Radar prospek (volume spike + scoring)
  GET  /api/signal/<t>     - Sinyal lengkap (fund + tech) + chart data
  POST /api/build_master   - Trigger rebuild master data (background)
  GET  /api/backtest/<t>   - Backtest 1 ticker
  GET  /api/cache/stats    - Statistik cache
  POST /api/cache/clear    - Bersihkan cache
"""

import logging
import os
import subprocess
import sys
import threading
import time
import json
import requests
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

import pandas as pd
from flask import Flask, jsonify, render_template, request

from modules.cache import Cache
from modules.scoring import (combine_signals, compute_sector_benchmarks,
                             score_fundamentals)
from modules.technical_analysis import chart_payload, compute_signals
from modules.backtest import backtest_ticker
from modules.alerts import run_alert_scan
from modules.decision import build_decisions, load_18langkah_current_step
from modules.export import build_summary, export_pdf, export_xlsx
from modules.position_sizing import calc_average, calc_position_size
from modules.telegram_notify import TelegramNotifier
from modules.trading_mode import get_config as get_trading_config
from modules.trading_mode import get_cut_loss_pct, get_take_profit_pct
from modules.canslim import evaluate_canslim, get_ihsg_status
from modules.dsn_mui import evaluate_dsn_mui
from modules.rebalancer import compute_allocation, gold_rsi_from_history
from modules.budget_allocator import (
    allocate_budget, from_buy_decision, from_commodity, candidates_to_dict
)
from modules.global_factor import compute_global_factor
from modules.scoring import compute_trading_score, TS_ENTRY, TS_WATCHLIST
from modules.rotation_advisor import generate_rotation_suggestions
from modules import pegadaian as pgd
from modules.asset_aggregator import aggregate_all_assets
from modules import portfolio_snapshot as snap

# Optional scheduler
try:
    from modules.scheduler import start_scheduler
except Exception:
    start_scheduler = None

# Market hours (sesi IDX, kalender libur). Defensive import: kalau modul belum
# ada (versi pre-patch), pakai stub yang anggap pasar selalu buka.
try:
    from modules.market_hours import market_status, is_market_open
except Exception:  # pragma: no cover
    def market_status():  # type: ignore
        return {"session": "UNKNOWN", "is_market_open": False, "badge": "?"}

    def is_market_open():  # type: ignore
        return False


# ----------------------------- VERSION ----------------------------- #
APP_VERSION = "2.1.0-patch-perbaikan-2026-05"


# ----------------------------- LOGGING ----------------------------- #
# Single logger setup — sebelumnya pakai print() bertebaran. Sekarang mirror
# ke stderr supaya muncul di gunicorn_error.log / launchd_stderr.log.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sharia.app")

# ----------------------------- CONFIG ----------------------------- #

# BASE_DIR otomatis: lokasi file app.py ini
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "portfolio.csv")
JII_FILE = os.path.join(BASE_DIR, "daftar_saham_syariah.csv")
MASTER_FILE = os.path.join(BASE_DIR, "master_data_syariah.csv")
PEGADAIAN_FILE = os.path.join(BASE_DIR, "pegadaian_transactions.csv")
BROKER_TX_FILE = os.path.join(BASE_DIR, "broker_transactions.csv")
SNAPSHOT_FILE = os.path.join(BASE_DIR, "portfolio_snapshots.csv")
CACHE_DIR = os.path.join(BASE_DIR, "cache")

# ----------------------------- CACHE TTL / PERIOD (tersentral) ----------------------------- #
# Disentralkan agar konsisten lintas endpoint & mudah di-tune via env. Saat
# pasar IDX tutup, TTL otomatis diperpanjang min 6 jam oleh cache._effective_ttl.
#   SCAN_PERIOD : window history untuk scoring teknikal (MA50/MACD butuh >= 50
#                 bar; 6mo (~126 bar) lebih robust dekat hari libur daripada 3mo).
#   SCAN_TTL_MIN: TTL menit untuk history scan saat pasar buka.
SCAN_PERIOD = os.environ.get("SCAN_PERIOD", "6mo")
SCAN_TTL_MIN = int(os.environ.get("SCAN_TTL_MIN", "60"))
# Minimum bar agar indikator (terutama MA50/MACD) dianggap reliabel.
MIN_BARS_RELIABLE = 50


# ----------------------------- PORTFOLIO I/O SAFETY ----------------------------- #
# Multi-worker gunicorn (atau dev mode dengan reloader) bisa baca→modifikasi→tulis
# portfolio.csv secara concurrent dan menyebabkan corrupted file. Pakai:
#   (1) threading.Lock untuk serialize akses,
#   (2) atomic write (tmp file → os.replace) supaya tidak ada partial write.
_PORTFOLIO_LOCK = threading.Lock()


def _atomic_write_csv(df: pd.DataFrame, dest_path: str) -> None:
    """Tulis DataFrame ke CSV secara atomic untuk hindari file corrupt."""
    tmp_path = dest_path + ".tmp"
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, dest_path)


# =========== ASSET AGGREGATOR (Single Source of Truth) ============ #
# Cache hasil aggregate selama beberapa detik untuk hindari race condition
# antara multiple endpoint yang panggil aggregator dalam 1 request dashboard.
_ASSETS_CACHE = {"data": None, "ts": 0}
_ASSETS_TTL = 5  # detik


def _get_current_price_for_aggregator(ticker: str) -> float:
    """Price fetcher untuk asset_aggregator: pakai cache history → fallback master_df.MP."""
    if not ticker:
        return 0.0
    t = ticker.upper()
    if t in ("EMAS", "EMAS_ANTAM"):
        try:
            return get_current_gold_price()
        except Exception:
            return 0.0
    try:
        hist = cache.get_history(t, period="3mo", ttl_minutes=60)
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    # Fallback: master_df.MP
    try:
        mdf = _load_master()
        if not mdf.empty:
            row = mdf[mdf["Ticker"] == t]
            if not row.empty:
                return float(row.iloc[0].get("MP", 0) or 0)
    except Exception:
        pass
    return 0.0


def _pegadaian_price_for_aggregator() -> float:
    """Wrapper untuk current price emas Pegadaian (sudah dibuat di endpoint Pegadaian)."""
    try:
        return _pegadaian_current_price()
    except Exception:
        return 0.0


def get_canonical_assets(force_refresh: bool = False):
    """SINGLE SOURCE OF TRUTH untuk total aset.
    Dipanggil oleh /api/dashboard, /api/broker_portfolio, /api/portfolio.
    Hasilnya di-cache 5 detik supaya tidak hitung ulang berkali-kali per request."""
    now = time.time()
    if (not force_refresh
            and _ASSETS_CACHE["data"] is not None
            and (now - _ASSETS_CACHE["ts"]) < _ASSETS_TTL):
        return _ASSETS_CACHE["data"]

    result = aggregate_all_assets(
        broker_tx_path=BROKER_TX_FILE,
        portfolio_csv_path=PORTFOLIO_FILE,
        pegadaian_tx_path=PEGADAIAN_FILE,
        get_current_price=_get_current_price_for_aggregator,
        get_gold_price_per_gram=_pegadaian_price_for_aggregator,
    )
    _ASSETS_CACHE["data"] = result
    _ASSETS_CACHE["ts"] = now
    return result
# (Endpoint /api/assets/canonical didaftarkan setelah `app = Flask()` di bawah)

app = Flask(__name__)
cache = Cache(CACHE_DIR)


# Endpoint debug aggregator (didaftarkan setelah `app` ada)
@app.route("/api/assets/canonical", methods=["GET"])
def assets_canonical():
    """Endpoint debug: lihat output aggregator langsung."""
    force = request.args.get("refresh", "0") == "1"
    return jsonify(get_canonical_assets(force_refresh=force))


# ----------------------------- HELPERS ----------------------------- #

def _load_master() -> pd.DataFrame:
    if not os.path.exists(MASTER_FILE):
        return pd.DataFrame()
    return pd.read_csv(MASTER_FILE, keep_default_na=False)


def _data_freshness() -> dict:
    """Umur data harga (history cache) untuk indikator freshness di UI.

    Mengambil file cache history TERBARU yang ditulis dan menghitung umurnya.
    Saat pasar tutup, cache sengaja diperpanjang (lihat cache._effective_ttl),
    jadi 'umur' bisa beberapa jam — itu wajar dan ditandai market_open=False.
    """
    history_dir = os.path.join(CACHE_DIR, "history")
    newest_mtime = 0.0
    try:
        with os.scandir(history_dir) as it:
            for entry in it:
                if entry.name.endswith(".csv"):
                    m = entry.stat().st_mtime
                    if m > newest_mtime:
                        newest_mtime = m
    except Exception:
        pass

    age_min = None
    label = "Tidak diketahui"
    if newest_mtime > 0:
        age_min = max(0.0, (time.time() - newest_mtime) / 60.0)
        if age_min < 1:
            label = "Baru saja"
        elif age_min < 60:
            label = f"{int(age_min)} menit lalu"
        elif age_min < 24 * 60:
            label = f"{age_min / 60:.1f} jam lalu"
        else:
            label = f"{age_min / (24 * 60):.1f} hari lalu"

    try:
        mkt_open = bool(is_market_open())
    except Exception:
        mkt_open = False

    return {
        "age_minutes": round(age_min, 1) if age_min is not None else None,
        "label": label,
        "market_open": mkt_open,
        "scan_period": SCAN_PERIOD,
    }


def _usdidr_rate() -> float:
    """Kurs USD→IDR terkini (cache 60 menit, fallback 16000)."""
    try:
        fx = cache.get_history("USDIDR=X", period="5d", ttl_minutes=60)
        if fx is not None and not fx.empty:
            return float(fx["Close"].iloc[-1])
    except Exception:
        pass
    return 16000.0


def _compute_us_portfolio() -> dict:
    """Hitung nilai portofolio saham US (dari portfolio_us.csv) dalam USD & Rp.

    Reusable oleh /api/dashboard dan /api/portfolio/global supaya konsisten.
    Mengembalikan dict: holdings, value_rp, invested_rp, pnl_rp, pnl_pct, usdidr.
    """
    out = {
        "holdings": [], "value_usd": 0.0, "value_rp": 0.0,
        "invested_usd": 0.0, "invested_rp": 0.0,
        "pnl_rp": 0.0, "pnl_pct": 0.0, "usdidr": _usdidr_rate(),
    }
    if not os.path.exists(US_PORTFOLIO_FILE):
        return out
    try:
        usdf = pd.read_csv(US_PORTFOLIO_FILE)
    except Exception:
        return out
    if usdf.empty:
        return out

    usdidr = out["usdidr"]
    try:
        _prefetch_histories(usdf["Ticker"].tolist(), period="5d",
                            ttl_minutes=60, market="US")
    except Exception:
        pass

    value_usd = 0.0
    invested_usd = 0.0
    holdings = []
    for _, row in usdf.iterrows():
        tk = str(row["Ticker"]).upper()
        harga_beli = float(row.get("Harga Beli", 0) or 0)
        lot = float(row.get("Jumlah Lot", 0) or 0)
        try:
            h = cache.get_history(tk, period="5d", ttl_minutes=60, market="US")
            cur = float(h["Close"].iloc[-1]) if h is not None and not h.empty else harga_beli
        except Exception:
            cur = harga_beli
        val = cur * lot
        cost = harga_beli * lot
        value_usd += val
        invested_usd += cost
        pnl_usd = val - cost
        holdings.append({
            "ticker": tk,
            "platform": "Saham US",
            "lot": lot,
            "avg_price_usd": round(harga_beli, 2),
            "current_price_usd": round(cur, 2),
            "value_usd": round(val, 2),
            "value_rp": round(val * usdidr, 0),
            "pnl_rp": round(pnl_usd * usdidr, 0),
            "pnl_pct": round((pnl_usd / cost * 100) if cost > 0 else 0, 2),
        })

    out["holdings"] = holdings
    out["value_usd"] = round(value_usd, 2)
    out["value_rp"] = round(value_usd * usdidr, 0)
    out["invested_usd"] = round(invested_usd, 2)
    out["invested_rp"] = round(invested_usd * usdidr, 0)
    out["pnl_rp"] = round((value_usd - invested_usd) * usdidr, 0)
    out["pnl_pct"] = round(((value_usd - invested_usd) / invested_usd * 100) if invested_usd > 0 else 0, 2)
    return out


def _master_row(master_df: pd.DataFrame, ticker: str) -> dict:
    if master_df.empty:
        return {}
    match = master_df[master_df["Ticker"] == ticker.upper()]
    if match.empty:
        return {}
    row = match.iloc[0]
    return {
        "sector": row.get("Sektor", "N/A"),
        "name": row.get("Nama Perusahaan", ""),
        "metrics": {
            "eps_growth": row.get("EPS QnQ"),
            "roa": row.get("ROA"),                 # Paket B
            "roe": row.get("ROE"),
            "per": row.get("PER"),
            "pbv": row.get("PBV"),
            "der": row.get("DER"),
            "dividend_yield": row.get("Dividend Yield"),
            "bvps": row.get("BVPS"),               # Paket B
            "market_price": row.get("MP"),         # Paket B
        }
    }


def _apply_intraday(hist, iq):
    """Suntik bar intraday TradingView (delayed) ke deret harga agar sinyal teknikal
    memakai data terkini. Aman: hanya jika harga valid; bar hari ini di-update,
    selainnya di-append sebagai bar baru. Mengembalikan DataFrame baru (tak mutasi asli)."""
    if hist is None or hist.empty or not iq:
        return hist
    try:
        last = float(iq.get("last") if iq.get("last") is not None else iq.get("close"))
    except (TypeError, ValueError):
        return hist
    if last <= 0:
        return hist
    try:
        from modules.time_sync import now_wib
        today = now_wib().date()
    except Exception:
        today = None

    h = hist.copy()
    cols = h.columns
    idx_last = h.index[-1]
    last_date = idx_last.date() if hasattr(idx_last, "date") else None

    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    o, hi, lo, vol = _f(iq.get("open")), _f(iq.get("high")), _f(iq.get("low")), _f(iq.get("volume"))

    if today is not None and last_date == today:
        # Update bar hari ini dengan data TradingView terkini
        if "Close" in cols:
            h.loc[idx_last, "Close"] = last
        if "High" in cols and hi is not None:
            h.loc[idx_last, "High"] = max(float(h.loc[idx_last, "High"]), hi, last)
        if "Low" in cols and lo is not None:
            h.loc[idx_last, "Low"] = min(float(h.loc[idx_last, "Low"]), lo, last)
        if "Volume" in cols and vol is not None:
            h.loc[idx_last, "Volume"] = vol
    elif today is not None:
        # Tambah bar baru untuk hari ini (mis. pra-pembukaan yfinance belum ada)
        try:
            import pandas as _pd
            new_idx = _pd.Timestamp(today)
            tzinfo = getattr(idx_last, "tz", None) or getattr(idx_last, "tzinfo", None)
            if tzinfo is not None:
                new_idx = new_idx.tz_localize(tzinfo)
            row = {}
            for c in cols:
                if c == "Open":
                    row[c] = o if o is not None else last
                elif c == "High":
                    row[c] = hi if hi is not None else last
                elif c == "Low":
                    row[c] = lo if lo is not None else last
                elif c == "Close":
                    row[c] = last
                elif c == "Volume":
                    row[c] = vol if vol is not None else 0.0
                else:
                    row[c] = float("nan")
            h.loc[new_idx] = row
        except Exception:
            # Gagal append → minimal update close bar terakhir agar harga terkini terpakai
            if "Close" in cols:
                h.loc[idx_last, "Close"] = last
    return h


def _evaluate(ticker: str, master_df: pd.DataFrame, benchmarks: dict, intraday=None) -> dict:
    """Hitung sinyal fundamental + teknikal untuk satu ticker.

    intraday: quote TradingView (delayed) opsional. Bila ada, disuntik ke deret harga
    agar sinyal & current_price memakai data terkini (Funnel mode live)."""
    info = _master_row(master_df, ticker)
    sector = info.get("sector")
    metrics = info.get("metrics", {})

    fund = score_fundamentals(metrics, sector=sector, benchmarks=benchmarks)

    hist = cache.get_history(ticker, period=SCAN_PERIOD, ttl_minutes=SCAN_TTL_MIN)
    if intraday:
        hist = _apply_intraday(hist, intraday)
    if hist is not None and not hist.empty:
        tech = compute_signals(hist)
    else:
        tech = {"signal": "NO DATA", "score": 0, "reasons": ["Data harga tidak tersedia"]}

    combined = combine_signals(fund, tech)

    return {
        "ticker": ticker.upper(),
        "name": info.get("name", ""),
        "sector": sector or "N/A",
        "fundamental": fund,
        "technical": tech,
        "combined": combined,
        "current_price": tech.get("last_close"),
        "price_source": "tradingview_delayed" if intraday else "yfinance",
        "metrics": metrics
    }


# Jumlah worker untuk prefetch concurrent. Dibatasi agar tidak memicu rate-limit
# Yahoo Finance. Override via env PREFETCH_WORKERS.
_PREFETCH_WORKERS = int(os.environ.get("PREFETCH_WORKERS", "8"))


def _prefetch_histories(
    tickers,
    period: str = "3mo",
    ttl_minutes: int = 60,
    market=None,
) -> None:
    """Warming cache history secara concurrent.

    Memanggil cache.get_history() paralel agar fetch yfinance (I/O-bound) untuk
    banyak ticker tidak dilakukan satu-per-satu (sequential). Aman karena tiap
    ticker menulis file cache berbeda; kalau cache masih fresh, call ini langsung
    return dari disk (murah). Exception per-ticker ditelan supaya satu ticker
    gagal tidak menggagalkan keseluruhan warming.
    """
    uniq = []
    seen = set()
    for t in tickers:
        if not t:
            continue
        key = str(t).upper().strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(t)
    if not uniq:
        return

    def _warm(tk):
        try:
            cache.get_history(tk, period=period, ttl_minutes=ttl_minutes, market=market)
        except Exception as e:  # pragma: no cover — defensive
            log.debug("prefetch %s failed: %s", tk, e)

    workers = max(1, min(_PREFETCH_WORKERS, len(uniq)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_warm, uniq))


# ----------------------------- SHORT-TTL RESPONSE MEMOIZE ----------------------------- #
# Endpoint agregat dashboard memanggil /api/all_stocks (3x), /api/decisions (2x),
# /api/prospects via test_client dalam SATU request → recompute berulang yang mahal.
# Memoize body JSON per (endpoint, query-string) selama beberapa detik agar
# panggilan duplikat di dalam satu siklus dashboard (dan refresh browser yang
# berdekatan) langsung di-serve dari memori. Aman untuk GET idempoten.
_RESP_MEMO: dict = {}
_RESP_MEMO_LOCK = threading.Lock()


def memoize_json(ttl_seconds: int = 20):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                key = (fn.__name__, request.full_path)
            except Exception:
                return fn(*args, **kwargs)
            now = time.time()
            with _RESP_MEMO_LOCK:
                hit = _RESP_MEMO.get(key)
                if hit is not None and (now - hit[1]) < ttl_seconds:
                    return app.response_class(hit[0], mimetype="application/json")
            resp = fn(*args, **kwargs)
            try:
                body = resp.get_data(as_text=True)
                with _RESP_MEMO_LOCK:
                    _RESP_MEMO[key] = (body, now)
            except Exception:
                pass
            return resp
        return wrapper
    return decorator


def _invalidate_response_memo():
    """Bersihkan memo (dipanggil setelah mutasi data portfolio/transaksi)."""
    with _RESP_MEMO_LOCK:
        _RESP_MEMO.clear()


# ----------------------------- ROUTES: PAGES ----------------------------- #

@app.route("/")
def index():
    return render_template("index.html")


# ----------------------------- HELPERS: PREDICTION LOGS & ADAPTIVE CORRECTION ----------------------------- #

PRED_LOG_FILE = os.path.join(CACHE_DIR, "prediction_logs.json")

def update_and_get_accuracy(pred_type: str, history_points: list) -> tuple:
    """
    Sinkronisasi prediksi dengan data aktual, menghitung akurasi historis,
    dan menghitung rata-rata bias untuk koreksi algoritma peramalan.
    
    Returns:
        tuple: (average_accuracy, bias_correction)
    """
    try:
        logs = {}
        if os.path.exists(PRED_LOG_FILE):
            with open(PRED_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        
        if pred_type not in logs:
            logs[pred_type] = []
            
        records = logs[pred_type]
        hist_dict = {point["date"]: point["price"] for point in history_points}
        
        updated = False
        for record in records:
            if record.get("actual_price") is None:
                t_date = record.get("target_date")
                actual = hist_dict.get(t_date)
                if actual is None:
                    sorted_dates = sorted([d for d in hist_dict.keys() if d >= t_date])
                    if sorted_dates:
                        actual = hist_dict[sorted_dates[0]]
                
                if actual is not None:
                    record["actual_price"] = actual
                    error_pct = (abs(actual - record["predicted_price"]) / actual) * 100.0
                    record["accuracy"] = round(max(0.0, 100.0 - error_pct), 4)
                    updated = True
                    
        if updated:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(PRED_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2)
                
        realized_records = [r for r in records if r.get("accuracy") is not None]
        
        K = 10
        recent_records = realized_records[-K:] if len(realized_records) >= K else realized_records
        
        if not recent_records:
            return None, 0.0
            
        avg_accuracy = sum(r["accuracy"] for r in recent_records) / len(recent_records)
        mean_error = sum(r["actual_price"] - r["predicted_price"] for r in recent_records) / len(recent_records)
        
        learning_rate = 0.5
        bias_correction = mean_error * learning_rate
        
        return round(avg_accuracy, 2), round(bias_correction, 2)
        
    except Exception as e:
        print(f"[prediction_feedback] Error updating accuracy for {pred_type}: {e}")
        return None, 0.0

def log_prediction(pred_type: str, made_on: str, target_date: str, predicted_price: float):
    """
    Mencatat prediksi baru ke dalam berkas log tanpa duplikasi.
    """
    try:
        logs = {}
        if os.path.exists(PRED_LOG_FILE):
            with open(PRED_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
                
        if pred_type not in logs:
            logs[pred_type] = []
            
        records = logs[pred_type]
        
        exists = False
        for record in records:
            if record.get("made_on") == made_on and record.get("target_date") == target_date:
                record["predicted_price"] = round(predicted_price, 2)
                exists = True
                break
                
        if not exists:
            records.append({
                "made_on": made_on,
                "target_date": target_date,
                "predicted_price": round(predicted_price, 2),
                "actual_price": None,
                "accuracy": None
            })
            
        if len(records) > 200:
            logs[pred_type] = records[-200:]
            
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(PRED_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)
            
    except Exception as e:
        print(f"[prediction_feedback] Error logging prediction for {pred_type}: {e}")


# ----------------------------- HELPERS: GOLD ----------------------------- #

def get_current_gold_price() -> float:
    """Mengambil harga emas Antam 1 gram saat ini."""
    # 1. Coba dari API logam-mulia-api
    try:
        url = "https://logam-mulia-api.iamutaki.workers.dev/api/prices/logammulia"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("data"):
                # Cari weight == 1 dan materialType == "Emas Batangan"
                for item in data["data"]:
                    if item.get("weight") == 1 and item.get("materialType") == "Emas Batangan":
                        val = float(item.get("sellPrice", 0))
                        if val > 0:
                            return val
    except Exception as e:
        print(f"[gold] API fetch error: {e}")
        
    # 2. Fallback ke yfinance (GC=F + USDIDR=X * 1.0828)
    try:
        gc_df = cache.get_history("GC=F", period="5d", ttl_minutes=60)
        usdidr_df = cache.get_history("USDIDR=X", period="5d", ttl_minutes=60)
        if gc_df is not None and usdidr_df is not None and not gc_df.empty and not usdidr_df.empty:
            gc_price = float(gc_df["Close"].iloc[-1])
            usdidr_price = float(usdidr_df["Close"].iloc[-1])
            calculated = (gc_price / 31.1034768) * usdidr_price * 1.0828
            return round(calculated, 2)
    except Exception as e:
        print(f"[gold] yfinance fallback error: {e}")
        
    # 3. Baseline hardcoded fallback
    return 2773000.0


# ----------------------------- ROUTES: PORTFOLIO ----------------------------- #

@app.route("/api/portfolio", methods=["GET"])
def get_portfolio():
    # SINKRONISASI: trigger aggregator yang AUTO-SYNC portfolio.csv dari
    # broker_transactions.csv (master source). Setelah ini, portfolio.csv selalu
    # mencerminkan holdings broker yang terbaru.
    try:
        get_canonical_assets()
    except Exception as e:
        print(f"[portfolio] aggregator sync failed: {e}")

    if not os.path.exists(PORTFOLIO_FILE):
        return jsonify([])

    df = pd.read_csv(PORTFOLIO_FILE)
    if df.empty:
        return jsonify([])

    master_df = _load_master()
    benchmarks = compute_sector_benchmarks(master_df) if not master_df.empty else {}

    results = []
    for _, row in df.iterrows():
        ticker = row["Ticker"]
        harga_beli = float(row["Harga Beli"])
        lot = int(row["Jumlah Lot"])

        if ticker == "EMAS" or ticker == "EMAS_ANTAM":
            current_gold = get_current_gold_price()
            pnl = ((current_gold - harga_beli) / harga_beli * 100) if harga_beli > 0 else 0.0
            cl = get_cut_loss_pct()
            tp = get_take_profit_pct()
            aksi = "HOLD"
            css = "hold"
            if pnl <= cl:
                aksi = "SELL (CUT LOSS)"
                css = "sell"
            elif pnl >= tp:
                aksi = "SELL (TAKE PROFIT)"
                css = "buy"
                
            results.append({
                "ticker": ticker,
                "name": "Emas LM Antam",
                "sector": "Komoditas",
                "harga_beli": harga_beli,
                "lot": lot,
                "sekarang": round(current_gold, 2),
                "pnl": round(pnl, 2),
                "stars": "⭐⭐⭐⭐⭐",
                "fundamental_score": 100,
                "fundamental_max": 100,
                "technical_signal": "N/A",
                "rsi": None,
                "ma_cross": "N/A",
                "aksi": aksi,
                "status_class": css,
                "jalur7": None
            })
            continue

        evaluation = _evaluate(ticker, master_df, benchmarks)
        current = evaluation["current_price"] or 0.0
        pnl = ((current - harga_beli) / harga_beli * 100) if harga_beli > 0 else 0.0

        # Override aksi kalau loss/profit melebihi threshold
        aksi = evaluation["combined"]["final_signal"]
        css = evaluation["combined"]["css_class"]
        # Threshold sesuai TRADING_MODE (swing/scalping/position)
        cl = get_cut_loss_pct()
        tp = get_take_profit_pct()
        if pnl <= cl:
            aksi = "SELL (CUT LOSS)"
            css = "sell"
        elif pnl >= tp:
            aksi = "SELL (TAKE PROFIT)"
            css = "buy"

        results.append({
            "ticker": ticker,
            "name": evaluation["name"],
            "sector": evaluation["sector"],
            "harga_beli": harga_beli,
            "lot": lot,
            "sekarang": round(current, 2),
            "pnl": round(pnl, 2),
            "stars": evaluation["fundamental"]["stars"],
            "fundamental_score": evaluation["fundamental"]["score"],
            "fundamental_max": evaluation["fundamental"]["max_score"],
            "technical_signal": evaluation["technical"].get("signal"),
            "rsi": evaluation["technical"].get("rsi"),
            "ma_cross": evaluation["technical"].get("ma_cross"),
            "aksi": aksi,
            "status_class": css,
            "jalur7": evaluation["technical"].get("jalur7"),
        })
    return jsonify(results)


@app.route("/api/portfolio", methods=["POST"])
def add_portfolio():
    data = request.json or {}
    ticker = str(data.get("ticker", "")).upper().strip()
    try:
        harga = float(data.get("harga", 0))
        lot = int(data.get("lot", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid number"}), 400

    if not ticker or harga <= 0 or lot <= 0:
        return jsonify({"success": False, "error": "Invalid data"}), 400

    with _PORTFOLIO_LOCK:
        df = pd.DataFrame()
        if os.path.exists(PORTFOLIO_FILE):
            df = pd.read_csv(PORTFOLIO_FILE)

        if not df.empty and ticker in df["Ticker"].values:
            df.loc[df["Ticker"] == ticker, "Harga Beli"] = harga
            df.loc[df["Ticker"] == ticker, "Jumlah Lot"] = lot
        else:
            new_row = pd.DataFrame([{
                "Ticker": ticker, "Harga Beli": harga, "Jumlah Lot": lot
            }])
            df = pd.concat([df, new_row], ignore_index=True) if not df.empty else new_row

        _atomic_write_csv(df, PORTFOLIO_FILE)
    _invalidate_response_memo()
    return jsonify({"success": True})


@app.route("/api/portfolio/<ticker>", methods=["DELETE"])
def delete_portfolio(ticker):
    if not os.path.exists(PORTFOLIO_FILE):
        return jsonify({"success": False}), 404
    with _PORTFOLIO_LOCK:
        df = pd.read_csv(PORTFOLIO_FILE)
        df = df[df["Ticker"] != ticker.upper()]
        _atomic_write_csv(df, PORTFOLIO_FILE)
    _invalidate_response_memo()
    return jsonify({"success": True})


def _compute_cash_flow() -> dict:
    """Ringkasan arus kas / sirkulasi modal lintas broker + Pegadaian.

    deposit_rp  : total TopUp (modal masuk)
    withdrawal_rp: total Withdrawal (modal keluar)
    buy_rp / sell_rp: nilai pembelian / penjualan aset
    realized_pnl_rp : realized P/L dari transaksi SELL saham
    net_modal_rp: deposit - withdrawal (modal bersih yang disetor)
    """
    cf = {
        "deposit_rp": 0.0, "withdrawal_rp": 0.0,
        "buy_rp": 0.0, "sell_rp": 0.0, "realized_pnl_rp": 0.0,
        "n_buy": 0, "n_sell": 0, "by_platform": {},
    }
    # ---- Broker transactions ----
    if os.path.exists(BROKER_TX_FILE):
        try:
            df = pd.read_csv(BROKER_TX_FILE)
            for _, r in df.iterrows():
                plat = str(r.get("platform") or "Bibit")
                tipe = str(r.get("tipe") or "").upper()
                nominal = float(r.get("nominal") or 0) if pd.notna(r.get("nominal")) else 0.0
                pnl = float(r.get("pnl_rp") or 0) if pd.notna(r.get("pnl_rp")) else 0.0
                bucket = cf["by_platform"].setdefault(
                    plat, {"deposit_rp": 0.0, "withdrawal_rp": 0.0,
                           "buy_rp": 0.0, "sell_rp": 0.0, "realized_pnl_rp": 0.0})
                if tipe == "TOPUP":
                    cf["deposit_rp"] += nominal; bucket["deposit_rp"] += nominal
                elif tipe == "WITHDRAWAL":
                    cf["withdrawal_rp"] += nominal; bucket["withdrawal_rp"] += nominal
                elif tipe == "BUY":
                    cf["buy_rp"] += nominal; cf["n_buy"] += 1; bucket["buy_rp"] += nominal
                elif tipe == "SELL":
                    cf["sell_rp"] += nominal; cf["n_sell"] += 1; bucket["sell_rp"] += nominal
                    cf["realized_pnl_rp"] += pnl; bucket["realized_pnl_rp"] += pnl
        except Exception as e:
            log.warning("cash flow broker parse failed: %s", e)

    # ---- Pegadaian (emas) ----
    try:
        pgd_sum = pgd.summarize(PEGADAIAN_FILE, current_price_per_gram=0.0)
        topup = float(pgd_sum.get("total_topup_rp") or 0)
        wd = float(pgd_sum.get("total_withdrawal_rp") or 0)
        buy = float(pgd_sum.get("total_invested_rp") or 0)
        sell = float(pgd_sum.get("total_received_sell_rp") or 0)
        cf["deposit_rp"] += topup
        cf["withdrawal_rp"] += wd
        cf["buy_rp"] += buy
        cf["sell_rp"] += sell
        cf["by_platform"]["Pegadaian"] = {
            "deposit_rp": topup, "withdrawal_rp": wd,
            "buy_rp": buy, "sell_rp": sell, "realized_pnl_rp": 0.0,
        }
    except Exception as e:
        log.warning("cash flow pegadaian failed: %s", e)

    cf["net_modal_rp"] = round(cf["deposit_rp"] - cf["withdrawal_rp"], 0)
    for k in ("deposit_rp", "withdrawal_rp", "buy_rp", "sell_rp", "realized_pnl_rp"):
        cf[k] = round(cf[k], 0)
    return cf


@app.route("/api/portfolio/global", methods=["GET"])
def get_portfolio_global():
    """Pandangan GLOBAL semua aset: alokasi kelas aset (Saham IDX/US, Emas, Kas)
    dengan bobot % & pertumbuhan (P/L), arus kas, dan time-series net worth.
    """
    canonical = get_canonical_assets()
    breakdown = canonical.get("breakdown", {})
    stocks_idx_rp = float(breakdown.get("stocks_rp") or 0)
    gold_rp = float(breakdown.get("gold_rp") or 0)
    cash_rp = float(breakdown.get("cash_rp") or 0)

    # P/L per kelas
    idx_pnl = sum(float(h.get("pnl_rp") or 0) for h in canonical.get("holdings", []))
    gold_pnl = float((canonical.get("platforms", {}).get("Pegadaian", {}) or {}).get("unrealized_pnl_rp") or 0)

    # Saham US
    us = _compute_us_portfolio()
    us_rp = float(us.get("value_rp") or 0)
    us_pnl = float(us.get("pnl_rp") or 0)
    us_inv = float(us.get("invested_rp") or 0)

    def _cls(value, pnl, invested=None):
        inv = invested if invested is not None else max(0.0, value - pnl)
        return {
            "value_rp": round(value, 0),
            "invested_rp": round(inv, 0),
            "pnl_rp": round(pnl, 0),
            "pnl_pct": round((pnl / inv * 100) if inv > 0 else 0, 2),
        }

    classes = {
        "saham_idx": _cls(stocks_idx_rp, idx_pnl),
        "saham_us": _cls(us_rp, us_pnl, invested=us_inv),
        "emas": _cls(gold_rp, gold_pnl),
        "kas": {"value_rp": round(cash_rp, 0), "invested_rp": round(cash_rp, 0),
                "pnl_rp": 0, "pnl_pct": 0},
    }

    net_worth = stocks_idx_rp + us_rp + gold_rp + cash_rp
    # bobot %
    for c in classes.values():
        c["weight_pct"] = round((c["value_rp"] / net_worth * 100) if net_worth > 0 else 0, 1)

    # Pertumbuhan investasi (kelas berisiko saja, kas dikecualikan)
    risk_invested = classes["saham_idx"]["invested_rp"] + classes["saham_us"]["invested_rp"] + classes["emas"]["invested_rp"]
    risk_pnl = idx_pnl + us_pnl + gold_pnl
    growth_pct = round((risk_pnl / risk_invested * 100) if risk_invested > 0 else 0, 2)

    cash_flow = _compute_cash_flow()

    # ---- Snapshot harian (upsert) + time-series ----
    snap.record_snapshot(SNAPSHOT_FILE, {
        "net_worth_rp": net_worth,
        "saham_idx_rp": stocks_idx_rp,
        "saham_us_rp": us_rp,
        "emas_rp": gold_rp,
        "kas_rp": cash_rp,
        "invested_rp": risk_invested,
        "pnl_rp": risk_pnl,
    })
    snapshots = snap.load_snapshots(SNAPSHOT_FILE)
    growth = snap.compute_growth(snapshots)

    return jsonify({
        "net_worth_rp": round(net_worth, 0),
        "risk_invested_rp": round(risk_invested, 0),
        "risk_pnl_rp": round(risk_pnl, 0),
        "growth_pct": growth_pct,
        "asset_classes": classes,
        "cash_flow": cash_flow,
        "us_holdings": us.get("holdings", []),
        "usdidr": us.get("usdidr"),
        "snapshots": snapshots,
        "growth_timeseries": growth,
        "warnings": canonical.get("warnings", []),
    })
BROKER_TRANSACTIONS_FILE = os.path.join(BASE_DIR, "broker_transactions.csv")

# ----------------------------- ROUTES: BROKER PORTFOLIO ----------------------------- #

@app.route("/api/broker_portfolio", methods=["GET"])
def get_broker_portfolio():
    if not os.path.exists(BROKER_TRANSACTIONS_FILE):
        # Create file with headers if it doesn't exist
        with open(BROKER_TRANSACTIONS_FILE, "w", encoding="utf-8") as f:
            f.write("id,tanggal,platform,tipe,ticker,harga,jumlah,nominal,pnl_rp,pnl_pct,broker_fee,exchange_fee\n")

    df = pd.read_csv(BROKER_TRANSACTIONS_FILE)
    if "broker_fee" not in df.columns:
        df["broker_fee"] = 0.0
    if "exchange_fee" not in df.columns:
        df["exchange_fee"] = 0.0

    # Recalculate cash, holdings, and realized P/L
    cash = {"Bibit": 0.0, "Pluang": 0.0, "Profit Anywhere": 0.0}
    min_cash = {"Bibit": 0.0, "Pluang": 0.0, "Profit Anywhere": 0.0}
    total_topup_entered = {"Bibit": 0.0, "Pluang": 0.0, "Profit Anywhere": 0.0}
    
    holdings = {
        "Bibit": {},
        "Pluang": {},
        "Profit Anywhere": {}
    }
    
    # Sort transactions chronologically
    df_sorted = df.copy()
    if not df_sorted.empty:
        df_sorted["tanggal"] = pd.to_datetime(df_sorted["tanggal"])
        df_sorted = df_sorted.sort_values("tanggal").reset_index(drop=True)
    
    realized_pnl_rp = 0.0
    platform_realized_pnl = {"Bibit": 0.0, "Pluang": 0.0, "Profit Anywhere": 0.0}
    
    for _, row in df_sorted.iterrows():
        plat = row["platform"]
        tipe = row["tipe"]
        ticker = str(row["ticker"]).upper().strip() if not pd.isna(row["ticker"]) else ""
        harga = float(row["harga"]) if not pd.isna(row["harga"]) else 0.0
        jumlah = float(row["jumlah"]) if not pd.isna(row["jumlah"]) else 0.0
        nominal = float(row["nominal"]) if not pd.isna(row["nominal"]) else 0.0
        broker_fee = float(row.get("broker_fee", 0.0)) if not pd.isna(row.get("broker_fee", 0.0)) else 0.0
        exchange_fee = float(row.get("exchange_fee", 0.0)) if not pd.isna(row.get("exchange_fee", 0.0)) else 0.0
        
        if plat not in cash:
            cash[plat] = 0.0
            min_cash[plat] = 0.0
            total_topup_entered[plat] = 0.0
            holdings[plat] = {}
            platform_realized_pnl[plat] = 0.0
            
        if tipe == "TOPUP":
            cash[plat] += nominal
            total_topup_entered[plat] += nominal
        elif tipe == "WITHDRAWAL":
            cash[plat] -= nominal
            total_topup_entered[plat] -= nominal
        elif tipe == "BUY":
            total_cost = (harga * jumlah) + broker_fee + exchange_fee
            cash[plat] -= total_cost
            if ticker not in holdings[plat]:
                holdings[plat][ticker] = {"shares": 0.0, "total_cost": 0.0, "avg_price": 0.0}
            holdings[plat][ticker]["shares"] += jumlah
            holdings[plat][ticker]["total_cost"] += total_cost
            holdings[plat][ticker]["avg_price"] = holdings[plat][ticker]["total_cost"] / holdings[plat][ticker]["shares"]
        elif tipe == "SELL":
            total_rev = (harga * jumlah) - broker_fee - exchange_fee
            cash[plat] += total_rev
            if ticker in holdings[plat] and holdings[plat][ticker]["shares"] > 0:
                avg = holdings[plat][ticker]["avg_price"]
                cost_basis = avg * jumlah
                real_pnl = total_rev - cost_basis
                
                realized_pnl_rp += real_pnl
                platform_realized_pnl[plat] += real_pnl
                
                holdings[plat][ticker]["shares"] -= jumlah
                holdings[plat][ticker]["total_cost"] -= cost_basis
                if holdings[plat][ticker]["shares"] == 0:
                    del holdings[plat][ticker]
                    
        min_cash[plat] = min(min_cash[plat], cash[plat])

    # Apply adjustments for negative cash (implied deposit)
    platform_stock_values = {"Bibit": 0.0, "Pluang": 0.0, "Profit Anywhere": 0.0}
    platform_unrealized_pnl = {"Bibit": 0.0, "Pluang": 0.0, "Profit Anywhere": 0.0}
    
    for plat in list(cash.keys()):
        deficit = -min_cash[plat]
        if deficit > 0:
            cash[plat] += deficit
            total_topup_entered[plat] += deficit

    # Fetch current prices for active holdings
    master_df = _load_master()
    active_holdings = []
    total_stock_value = 0.0
    unrealized_pnl_rp = 0.0
    
    for plat, stocks in holdings.items():
        for ticker, h_data in list(stocks.items()):
            shares = h_data["shares"]
            if shares <= 0:
                continue
            avg_price = h_data["avg_price"]
            
            # Get current price
            current_price = 0.0
            if ticker == "EMAS" or ticker == "EMAS_ANTAM":
                current_price = get_current_gold_price()
            else:
                # Try to get from cache
                hist = cache.get_history(ticker, period="3mo", ttl_minutes=60)
                if hist is not None and not hist.empty:
                    current_price = float(hist['Close'].iloc[-1])
                else:
                    # Try master_df
                    if not master_df.empty:
                        row_m = master_df[master_df["Ticker"] == ticker]
                        if not row_m.empty:
                            current_price = float(row_m.iloc[0].get("MP", 0.0))
            
            if current_price == 0.0:
                current_price = avg_price # fallback
                
            cost_basis = avg_price * shares
            current_val = current_price * shares
            pnl_val = current_val - cost_basis
            pnl_pct = (pnl_val / cost_basis * 100) if cost_basis > 0 else 0.0
            
            total_stock_value += current_val
            unrealized_pnl_rp += pnl_val
            
            if plat not in platform_stock_values:
                platform_stock_values[plat] = 0.0
                platform_unrealized_pnl[plat] = 0.0
            platform_stock_values[plat] += current_val
            platform_unrealized_pnl[plat] += pnl_val
            
            # Fetch company name if available
            comp_name = ticker
            if ticker == "EMAS" or ticker == "EMAS_ANTAM":
                comp_name = "Emas LM Antam"
            elif not master_df.empty:
                row_m = master_df[master_df["Ticker"] == ticker]
                if not row_m.empty:
                    comp_name = str(row_m.iloc[0].get("Nama", ticker))
                    
            active_holdings.append({
                "platform": plat,
                "ticker": ticker,
                "name": comp_name,
                "avg_price": round(avg_price, 2),
                "shares": round(shares, 4), # Support fractional for Pluang
                "lot": round(shares, 4) if (ticker == "EMAS" or ticker == "EMAS_ANTAM") else round(shares / 100, 2),
                "current_price": round(current_price, 2),
                "current_value": round(current_val, 2),
                "pnl_rp": round(pnl_val, 2),
                "pnl_pct": round(pnl_pct, 2)
            })

    # Platform summaries
    platforms_summary = {}
    for plat in ["Bibit", "Pluang", "Profit Anywhere"]:
        c_val = cash.get(plat, 0.0)
        s_val = platform_stock_values.get(plat, 0.0)
        tot_val = c_val + s_val
        plat_topup = total_topup_entered.get(plat, 0.0)
        
        r_pnl = platform_realized_pnl.get(plat, 0.0)
        u_pnl = platform_unrealized_pnl.get(plat, 0.0)
        tot_pnl = r_pnl + u_pnl
        tot_pnl_pct = (tot_pnl / plat_topup * 100) if plat_topup > 0 else 0.0
        
        platforms_summary[plat] = {
            "cash": round(c_val, 2),
            "stock_value": round(s_val, 2),
            "total_value": round(tot_val, 2),
            "total_invested": round(plat_topup, 2),
            "pnl_rp": round(tot_pnl, 2),
            "pnl_pct": round(tot_pnl_pct, 2)
        }

    # Calculate overall summaries
    total_portfolio_value = sum(p["total_value"] for p in platforms_summary.values())
    total_portfolio_invested = sum(p["total_invested"] for p in platforms_summary.values())
    total_portfolio_realized_pnl = sum(platform_realized_pnl.values())
    total_portfolio_unrealized_pnl = unrealized_pnl_rp
    total_portfolio_pnl_rp = total_portfolio_realized_pnl + total_portfolio_unrealized_pnl
    total_portfolio_pnl_pct = (total_portfolio_pnl_rp / total_portfolio_invested * 100) if total_portfolio_invested > 0 else 0.0
        
    # Prepare transaction list (sorted by date desc)
    tx_list = []
    if not df.empty:
        df_display = df.copy()
        df_display = df_display.sort_values("tanggal", ascending=False)
        for _, row in df_display.iterrows():
            tx_list.append({
                "id": str(row["id"]),
                "tanggal": str(row["tanggal"]),
                "platform": str(row["platform"]),
                "tipe": str(row["tipe"]),
                "ticker": str(row["ticker"]) if not pd.isna(row["ticker"]) else "",
                "harga": float(row["harga"]) if not pd.isna(row["harga"]) else 0.0,
                "jumlah": float(row["jumlah"]) if not pd.isna(row["jumlah"]) else 0.0,
                "nominal": float(row["nominal"]) if not pd.isna(row["nominal"]) else 0.0,
                "pnl_rp": float(row["pnl_rp"]) if not pd.isna(row["pnl_rp"]) else 0.0,
                "pnl_pct": float(row["pnl_pct"]) if not pd.isna(row["pnl_pct"]) else 0.0,
                "broker_fee": float(row.get("broker_fee", 0.0)) if not pd.isna(row.get("broker_fee", 0.0)) else 0.0,
                "exchange_fee": float(row.get("exchange_fee", 0.0)) if not pd.isna(row.get("exchange_fee", 0.0)) else 0.0
            })
            
    # ============================================================
    # OVERRIDE: pakai aggregator (single source of truth) untuk summary.
    # Endpoint legacy ini tetap kembalikan tx_list dari broker_transactions.csv,
    # tapi nilai SUMMARY & HOLDINGS sekarang IDENTIK dengan /api/dashboard.
    # ============================================================
    canonical = get_canonical_assets()
    canonical_summary = {
        "total_value":      canonical["total_asset_rp"],
        "total_invested":   canonical["total_invested_rp"],
        "total_pnl_rp":     canonical["total_pnl_rp"],
        "total_pnl_pct":    canonical["total_pnl_pct"],
        "realized_pnl_rp":  canonical["total_realized_pnl_rp"],
        "unrealized_pnl_rp": canonical["total_unrealized_pnl_rp"],
        "platforms":        canonical["platforms"],
        "breakdown":        canonical["breakdown"],
        "warnings":         canonical.get("warnings", []),
        "sync_actions":     canonical.get("sync_actions", []),
    }

    return jsonify({
        "summary": canonical_summary,
        "holdings": canonical["holdings"],
        "transactions": tx_list,
    })

@app.route("/api/broker_portfolio/transaction", methods=["POST"])
def add_broker_transaction():
    data = request.json or {}
    tanggal = data.get("tanggal")
    platform = data.get("platform")
    tipe = data.get("tipe")
    ticker = str(data.get("ticker", "")).upper().strip()
    
    try:
        harga = float(data.get("harga", 0.0))
        jumlah = float(data.get("jumlah", 0.0))
        nominal = float(data.get("nominal", 0.0))
        broker_fee = float(data.get("broker_fee", 0.0))
        exchange_fee = float(data.get("exchange_fee", 0.0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Angka tidak valid"}), 400
        
    if not tanggal or not platform or not tipe:
        return jsonify({"success": False, "error": "Data tanggal, platform, dan tipe wajib diisi"}), 400
        
    # Validation based on transaction type
    if tipe in ["TOPUP", "WITHDRAWAL"]:
        if nominal <= 0:
            return jsonify({"success": False, "error": f"Nominal {tipe.lower()} harus lebih dari 0"}), 400
        harga = 0.0
        jumlah = 0.0
        ticker = ""
        broker_fee = 0.0
        exchange_fee = 0.0
    elif tipe in ["BUY", "SELL"]:
        if not ticker:
            return jsonify({"success": False, "error": "Ticker wajib diisi untuk transaksi Buy/Sell"}), 400
        if harga <= 0 or jumlah <= 0:
            return jsonify({"success": False, "error": "Harga dan jumlah wajib bernilai positif"}), 400
        
        if tipe == "BUY":
            nominal = (harga * jumlah) + broker_fee + exchange_fee
        else: # SELL
            nominal = (harga * jumlah) - broker_fee - exchange_fee
        
    # If SELL, calculate realized P/L
    pnl_rp = 0.0
    pnl_pct = 0.0
    if tipe == "SELL":
        # We need to find the average cost basis of this ticker on this platform before this sale.
        if os.path.exists(BROKER_TRANSACTIONS_FILE):
            df = pd.read_csv(BROKER_TRANSACTIONS_FILE)
            if not df.empty:
                if "broker_fee" not in df.columns:
                    df["broker_fee"] = 0.0
                if "exchange_fee" not in df.columns:
                    df["exchange_fee"] = 0.0
                df["tanggal"] = pd.to_datetime(df["tanggal"])
                df_sorted = df.sort_values("tanggal").reset_index(drop=True)
                
                temp_shares = 0.0
                temp_cost = 0.0
                temp_avg = 0.0
                
                for _, r in df_sorted.iterrows():
                    if r["platform"] == platform and r["ticker"] == ticker:
                        r_broker_fee = float(r["broker_fee"]) if not pd.isna(r["broker_fee"]) else 0.0
                        r_exchange_fee = float(r["exchange_fee"]) if not pd.isna(r["exchange_fee"]) else 0.0
                        if r["tipe"] == "BUY":
                            c = (float(r["harga"]) * float(r["jumlah"])) + r_broker_fee + r_exchange_fee
                            temp_shares += float(r["jumlah"])
                            temp_cost += c
                            temp_avg = temp_cost / temp_shares if temp_shares > 0 else 0.0
                        elif r["tipe"] == "SELL":
                            s_j = float(r["jumlah"])
                            temp_shares -= s_j
                            temp_cost -= (temp_avg * s_j)
                            if temp_shares == 0:
                                temp_shares = 0.0
                                temp_cost = 0.0
                                temp_avg = 0.0
                                
                if temp_shares > 0:
                    cost_basis = temp_avg * jumlah
                    pnl_rp = nominal - cost_basis
                    pnl_pct = (pnl_rp / cost_basis * 100) if cost_basis > 0 else 0.0
                    
    # Generate unique ID
    import time
    tx_id = f"tx_{int(time.time() * 1000)}"
    
    df_new = pd.DataFrame([{
        "id": tx_id,
        "tanggal": tanggal,
        "platform": platform,
        "tipe": tipe,
        "ticker": ticker,
        "harga": harga,
        "jumlah": jumlah,
        "nominal": nominal,
        "pnl_rp": pnl_rp,
        "pnl_pct": pnl_pct,
        "broker_fee": broker_fee,
        "exchange_fee": exchange_fee
    }])
    
    if os.path.exists(BROKER_TRANSACTIONS_FILE):
        df_all = pd.read_csv(BROKER_TRANSACTIONS_FILE)
        if "broker_fee" not in df_all.columns:
            df_all["broker_fee"] = 0.0
        if "exchange_fee" not in df_all.columns:
            df_all["exchange_fee"] = 0.0
        df_all = pd.concat([df_all, df_new], ignore_index=True)
    else:
        df_all = df_new
        
    df_all.to_csv(BROKER_TRANSACTIONS_FILE, index=False)
    _invalidate_response_memo()
    return jsonify({"success": True, "id": tx_id})

@app.route("/api/broker_portfolio/transaction/<tx_id>", methods=["DELETE"])
def delete_broker_transaction(tx_id):
    if not os.path.exists(BROKER_TRANSACTIONS_FILE):
        return jsonify({"success": False, "error": "File tidak ditemukan"}), 404
        
    df = pd.read_csv(BROKER_TRANSACTIONS_FILE)
    df = df[df["id"] != tx_id]
    df.to_csv(BROKER_TRANSACTIONS_FILE, index=False)
    _invalidate_response_memo()
    return jsonify({"success": True})

@app.route("/api/broker_portfolio/upload_screenshot", methods=["POST"])
def upload_portfolio_screenshot():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "Tidak ada berkas yang diunggah"}), 400
        
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "Nama berkas kosong"}), 400
        
    # Check for GEMINI_API_KEY
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        try:
            with open(os.path.join(BASE_DIR, ".env"), "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("GEMINI_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
        except:
            pass
            
    # Try parsing image filename as fallback/intelligent detection
    import re
    # Clean the filename for robust regex parsing (replace underscores, hyphens, and non-decimal dots with spaces)
    fn_clean = file.filename.replace("_", " ").replace("-", " ")
    fn_clean = re.sub(r'\.(?!\d)', ' ', fn_clean)
    fn_lower = fn_clean.lower()
    
    extracted_data = {
        "platform": "Bibit",
        "tipe": "BUY",
        "ticker": "BRIS",
        "harga": 2100.0,
        "jumlah": 500.0,
        "nominal": 1050000.0,
        "broker_fee": 0.0,
        "exchange_fee": 0.0,
        "note": "AI Extraction Fallback (Berdasarkan analisis cerdas nama file / tipe)"
    }
    
    # Filename heuristic detection
    if "pluang" in fn_lower:
        extracted_data["platform"] = "Pluang"
        extracted_data["jumlah"] = 2.5
        extracted_data["ticker"] = "PLNG"
        extracted_data["harga"] = 1000.0
        extracted_data["nominal"] = 2500.0
    elif "profit" in fn_lower or "anywhere" in fn_lower:
        extracted_data["platform"] = "Profit Anywhere"
    elif "stockbit" in fn_lower or "bibit" in fn_lower:
        extracted_data["platform"] = "Bibit"
        
    if "sell" in fn_lower or "jual" in fn_lower:
        extracted_data["tipe"] = "SELL"
    elif "topup" in fn_lower or "deposit" in fn_lower or "isi" in fn_lower:
        extracted_data["tipe"] = "TOPUP"
    elif "withdraw" in fn_lower or "tarik" in fn_lower:
        extracted_data["tipe"] = "WITHDRAWAL"
    else:
        extracted_data["tipe"] = "BUY"
        
    if extracted_data["tipe"] in ["TOPUP", "WITHDRAWAL"]:
        extracted_data["ticker"] = ""
        extracted_data["harga"] = 0.0
        extracted_data["jumlah"] = 0.0
        # For topups/withdrawals, look for any number as nominal
        numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', fn_clean)]
        if numbers:
            extracted_data["nominal"] = numbers[0]
        else:
            extracted_data["nominal"] = 5000000.0 if extracted_data["tipe"] == "TOPUP" else 1000000.0
    else:
        tickers_found = re.findall(r'\b[a-zA-Z]{4}\b', fn_clean)
        if tickers_found:
            for t in tickers_found:
                t_upper = t.upper()
                if t_upper not in ["SELL", "BULL", "BEAR", "CASH", "FILE", "JPEG", "PORT", "GOLD", "DROP", "LOAD", "LOGS", "LIST", "SHOW"]:
                    extracted_data["ticker"] = t_upper
                    break
                    
        # Extract numbers from filename for harga and jumlah
        lot_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:lot|l)\b', fn_lower)
        shares_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:lembar|shares|sh)\b', fn_lower)
        numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', fn_clean)]
        
        if lot_match:
            lot_val = float(lot_match.group(1))
            extracted_data["jumlah"] = lot_val * 100
            for num in numbers:
                if num != lot_val and 50 <= num <= 1000000:
                    extracted_data["harga"] = num
                    break
        elif shares_match:
            shares_val = float(shares_match.group(1))
            extracted_data["jumlah"] = shares_val
            for num in numbers:
                if num != shares_val and 50 <= num <= 1000000:
                    extracted_data["harga"] = num
                    break
        else:
            if len(numbers) >= 2:
                n_sorted = sorted(numbers)
                if n_sorted[0] <= 1000 and n_sorted[1] > 50:
                    if (extracted_data["platform"] in ["Bibit", "Profit Anywhere"]) and n_sorted[0] <= 200:
                        extracted_data["jumlah"] = n_sorted[0] * 100
                    else:
                        extracted_data["jumlah"] = n_sorted[0]
                    extracted_data["harga"] = n_sorted[1]
                else:
                    extracted_data["harga"] = n_sorted[1]
                    extracted_data["jumlah"] = n_sorted[0]
            elif len(numbers) == 1:
                if numbers[0] > 50:
                    extracted_data["harga"] = numbers[0]
                else:
                    if extracted_data["platform"] in ["Bibit", "Profit Anywhere"]:
                        extracted_data["jumlah"] = numbers[0] * 100
                    else:
                        extracted_data["jumlah"] = numbers[0]
                        
        extracted_data["nominal"] = extracted_data["harga"] * extracted_data["jumlah"]
            
    # If GEMINI_API_KEY is found, let's call the REST API for real!
    if api_key and api_key != "":
        try:
            import base64
            import json
            import urllib.request
            
            img_bytes = file.read()
            file.seek(0)
            
            mime_type = "image/png"
            if fn_lower.endswith(".jpg") or fn_lower.endswith(".jpeg"):
                mime_type = "image/jpeg"
            elif fn_lower.endswith(".webp"):
                mime_type = "image/webp"
                
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            
            prompt = """
            Anda adalah asisten ekstraksi data keuangan untuk Sharia Trading Assistant.
            Tugas Anda adalah membaca tangkapan layar (screenshot) bukti transaksi dari broker Bibit (atau Stockbit), Pluang, atau Profit Anywhere (Phintraco Sec).
            Ekstrak data transaksi dalam format JSON mentah dengan key berikut:
            {
              "platform": "Bibit" atau "Pluang" atau "Profit Anywhere" (Catatan: jika dari Stockbit, isi platform dengan "Bibit"),
              "tipe": "BUY" atau "SELL" atau "TOPUP" atau "WITHDRAWAL",
              "ticker": "KODE SAHAM" (kosong jika TOPUP atau WITHDRAWAL, misalnya "BBRI" atau "BRIS"),
              "harga": angka harga beli/jual per lembar saham (0 jika TOPUP atau WITHDRAWAL),
              "jumlah": angka lembar saham yang ditransaksikan (0 jika TOPUP atau WITHDRAWAL. Catatan: jika screenshot menunjukkan Lot, kalikan 100 untuk mendapatkan lembar saham. Misal 5 Lot = 500 lembar),
              "nominal": total uang transaksi dalam Rupiah (jika TOPUP atau WITHDRAWAL atau total buy/sell),
              "broker_fee": biaya broker/transaksi dalam Rupiah (opsional, default 0 jika tidak ada),
              "exchange_fee": biaya bursa/levy dalam Rupiah (opsional, default 0 jika tidak ada)
            }
            Keluarkan HANYA teks JSON yang valid tanpa markdown code block. Jika salah satu data tidak terlihat jelas, buat tebakan terbaik berdasarkan konteks visual gambar.
            """
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": img_b64
                                }
                            }
                        ]
                    }
                ]
            }
            
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=15) as res:
                res_data = json.loads(res.read().decode("utf-8"))
                text_out = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_out.startswith("```json"):
                    text_out = text_out[7:]
                if text_out.endswith("```"):
                    text_out = text_out[:-3]
                text_out = text_out.strip()
                
                parsed_json = json.loads(text_out)
                
                # Normalize and map platform to match frontend options
                platform_raw = parsed_json.get("platform", "Bibit").strip().lower()
                if platform_raw in ["stockbit", "bibit"]:
                    platform = "Bibit"
                elif platform_raw in ["pluang"]:
                    platform = "Pluang"
                elif platform_raw in ["profit anywhere", "phintraco", "profitanywhere"]:
                    platform = "Profit Anywhere"
                else:
                    platform = "Bibit"
                    
                extracted_data = {
                    "platform": platform,
                    "tipe": parsed_json.get("tipe", "BUY"),
                    "ticker": parsed_json.get("ticker", "").upper().strip(),
                    "harga": float(parsed_json.get("harga", 0.0)),
                    "jumlah": float(parsed_json.get("jumlah", 0.0)),
                    "nominal": float(parsed_json.get("nominal", 0.0)),
                    "broker_fee": float(parsed_json.get("broker_fee", 0.0)),
                    "exchange_fee": float(parsed_json.get("exchange_fee", 0.0)),
                    "note": "AI Extraction (Gemini 1.5 Flash)"
                }
        except Exception as e:
            extracted_data["note"] = f"AI Extraction Fallback (Gagal memanggil API: {str(e)})"
            
    return jsonify({
        "success": True,
        "data": extracted_data
    })


# ----------------------------- ROUTES: PROSPECTS ----------------------------- #

@app.route("/api/prospects", methods=["GET"])
@memoize_json(ttl_seconds=20)
def get_prospects():
    if not os.path.exists(JII_FILE):
        return jsonify([])

    df_input = pd.read_csv(JII_FILE)
    master_df = _load_master()
    benchmarks = compute_sector_benchmarks(master_df) if not master_df.empty else {}

    tickers = df_input["Ticker"].tolist()
    # Prefetch concurrent: warming cache history dulu agar loop di bawah (dan
    # _evaluate) hit disk, bukan fetch yfinance satu-per-satu (sequential).
    _prefetch_histories(tickers, period=SCAN_PERIOD, ttl_minutes=SCAN_TTL_MIN)

    # Intraday-aware: saat pasar BUKA, bar terakhir adalah sesi parsial hari
    # berjalan → volume-nya belum penuh sehingga rasio spike akan understated.
    # Maka pakai sesi penuh terakhir (bar kemarin) sebagai acuan "today".
    market_open_now = False
    try:
        market_open_now = bool(is_market_open())
    except Exception:
        market_open_now = False

    results = []
    for ticker in tickers:
        hist = cache.get_history(ticker, period=SCAN_PERIOD, ttl_minutes=SCAN_TTL_MIN)
        if hist is None or hist.empty or "Volume" not in hist.columns or len(hist) < 12:
            continue

        # Pilih indeks "hari ini" untuk deteksi spike: kalau market buka, abaikan
        # bar parsial terakhir dan pakai sesi penuh sebelumnya.
        last_idx = -2 if market_open_now else -1
        today_vol = float(hist["Volume"].iloc[last_idx])
        # Rata-rata 10 sesi penuh SEBELUM hari acuan.
        window = hist["Volume"].iloc[last_idx - 10:last_idx]
        avg_vol = float(window.mean()) if len(window) > 0 else 0.0
        if avg_vol <= 0:
            continue
        ratio = today_vol / avg_vol
        if ratio < 1.5 or today_vol < 1_000_000:
            continue

        evaluation = _evaluate(ticker, master_df, benchmarks)
        evaluation["volume_spike"] = round(ratio, 2)
        evaluation["volume_basis"] = "prev_full_session" if market_open_now else "latest"
        results.append(evaluation)

    # Urutkan: prioritas sinyal rekomendasi beli teratas, lalu skor fundamental, teknikal, dan volume spike
    signal_weights = {
        "STRONG BUY": 7,
        "BUY": 6,
        "ACCUMULATE": 5,
        "SPECULATIVE BUY": 4,
        "HOLD": 3,
        "WATCH (Tech Weak)": 2,
        "AVOID": 1
    }
    results.sort(
        key=lambda r: (
            signal_weights.get(r.get("combined", {}).get("final_signal"), 0),
            r.get("fundamental", {}).get("score", 0),
            r.get("technical", {}).get("score", 0),
            r.get("volume_spike", 0)
        ),
        reverse=True
    )
    return jsonify(results)


# ----------------------------- ROUTES: ALL STOCKS RANKING ----------------------------- #

@app.route("/api/all_stocks", methods=["GET"])
@memoize_json(ttl_seconds=20)
def get_all_stocks():
    """
    Scan SEMUA ticker di daftar_saham_syariah.csv tanpa filter volume.
    Return list dengan fundamental + technical scoring + sorting by skor.
    Query params:
        sort_by   = score|rsi|ticker|sector  (default: score)
        sector    = filter by sektor (optional)
        min_score = minimal fundamental score (optional, default 0)
    """
    if not os.path.exists(JII_FILE):
        return jsonify([])

    sort_by = request.args.get("sort_by", "score")
    sector_filter = request.args.get("sector", "").strip()
    try:
        min_score = int(request.args.get("min_score", 0))
    except ValueError:
        min_score = 0

    df_input = pd.read_csv(JII_FILE)
    master_df = _load_master()
    benchmarks = compute_sector_benchmarks(master_df) if not master_df.empty else {}

    # Mode LIVE: pakai data intraday TradingView (cache + on-demand utk saham
    # yang belum ter-cache, dibatasi). Tanpa live → tetap pakai cache TV bila ada
    # (gratis), tanpa on-demand → scan tetap cepat.
    live = request.args.get("live", "0") == "1"

    tickers = df_input["Ticker"].tolist()
    # Prefetch concurrent: warming cache sebelum _evaluate dipanggil per ticker.
    _prefetch_histories(tickers, period="3mo", ttl_minutes=60)

    intraday_map = {}
    try:
        from modules.tv_collector import get_intraday_bulk
        intraday_map = get_intraday_bulk(tickers, allow_ondemand=live)
    except Exception as e:
        app.logger.warning("intraday enrichment gagal: %s", e)

    results = []
    for ticker in tickers:
        evaluation = _evaluate(
            ticker, master_df, benchmarks,
            intraday=intraday_map.get(str(ticker).upper()),
        )

        # Filter by sektor
        if sector_filter and evaluation["sector"] != sector_filter:
            continue

        # Filter by min_score
        if evaluation["fundamental"]["score"] < min_score:
            continue

        results.append({
            "ticker": evaluation["ticker"],
            "name": evaluation["name"],
            "sector": evaluation["sector"],
            "current_price": evaluation["current_price"],
            "price_source": evaluation.get("price_source", "yfinance"),
            "fundamental_score": evaluation["fundamental"]["score"],
            "fundamental_max": evaluation["fundamental"]["max_score"],
            "stars": evaluation["fundamental"]["stars"],
            "fundamental_label": evaluation["fundamental"]["label"],
            "technical_signal": evaluation["technical"].get("signal"),
            "technical_score": evaluation["technical"].get("score"),
            "rsi": evaluation["technical"].get("rsi"),
            "ma_cross": evaluation["technical"].get("ma_cross"),
            "final_signal": evaluation["combined"]["final_signal"],
            "css_class": evaluation["combined"]["css_class"],
            "eps_growth": evaluation["metrics"].get("eps_growth"),
            "roe": evaluation["metrics"].get("roe"),
            "der": evaluation["metrics"].get("der"),
            "pbv": evaluation["metrics"].get("pbv"),
            "jalur7": evaluation["technical"].get("jalur7"),
            "reliable": evaluation["technical"].get("reliable", True),
            "data_points": evaluation["technical"].get("data_points"),
        })

    # Sorting
    if sort_by == "score":
        results.sort(key=lambda r: (r["fundamental_score"], r["technical_score"] or 0), reverse=True)
    elif sort_by == "rsi":
        results.sort(key=lambda r: r["rsi"] or 0, reverse=True)
    elif sort_by == "sector":
        results.sort(key=lambda r: (r["sector"], -r["fundamental_score"]))
    else:
        results.sort(key=lambda r: r["ticker"])

    # Sektor list untuk filter dropdown di UI
    sectors = sorted(set(r["sector"] for r in results if r["sector"] not in ("N/A", "")))

    n_tv = sum(1 for r in results if r.get("price_source") == "tradingview_delayed")
    return jsonify({
        "stocks": results,
        "total": len(results),
        "sectors": sectors,
        "sort_by": sort_by,
        "filters": {"sector": sector_filter, "min_score": min_score},
        "live": live,
        "n_tradingview": n_tv,
    })


# ----------------------------- ROUTES: SIGNAL DETAIL ----------------------------- #

@app.route("/api/signal/<ticker>", methods=["GET"])
def get_signal(ticker):
    """Return sinyal lengkap + chart data untuk modal detail."""
    master_df = _load_master()
    benchmarks = compute_sector_benchmarks(master_df) if not master_df.empty else {}

    evaluation = _evaluate(ticker, master_df, benchmarks)
    hist = cache.get_history(ticker, period="6mo", ttl_minutes=60)
    chart = chart_payload(hist, lookback=120) if hist is not None else {}

    # Enrichment: harga intraday TradingView (delayed) bila tersedia saat jam bursa.
    # Additif — tidak mengubah sinyal berbasis yfinance. None bila TV mati/di luar jam.
    try:
        from modules.tv_collector import get_intraday
        intraday = get_intraday(ticker)
    except Exception:
        intraday = None

    # Narasi AI (Claude API) bila tersedia di cache. None bila fitur nonaktif/tak ada.
    try:
        from modules.ai_narrative import get_narrative
        ai_narrative = get_narrative(ticker)
    except Exception:
        ai_narrative = None

    return jsonify({
        "ticker": ticker.upper(),
        "evaluation": evaluation,
        "chart": chart,
        "intraday": intraday,
        "ai_narrative": ai_narrative
    })


# ----------------------------- ROUTES: BACKTEST ----------------------------- #

@app.route("/api/backtest/<ticker>", methods=["GET"])
def get_backtest(ticker):
    period = request.args.get("period", "1y")
    df = cache.get_history(ticker, period=period, ttl_minutes=24 * 60)
    if df is None or df.empty:
        return jsonify({"error": "no data"}), 404
    result = backtest_ticker(df)
    return jsonify(result)


# ----------------------------- ROUTES: ADMIN ----------------------------- #

@app.route("/api/build_master", methods=["POST"])
def run_build_master():
    try:
        # Pakai sys.executable (bukan 'python3' dari PATH minimal launchd) supaya
        # subprocess mewarisi venv yang me-run aplikasi ini.
        subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, "build_master_data.py")],
            cwd=BASE_DIR,
        )
        return jsonify({"success": True, "message": "Proses background dimulai (~2 menit)."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/telegram/test", methods=["POST", "GET"])
def telegram_test():
    """Kirim test message ke Telegram untuk verifikasi setup."""
    notif = TelegramNotifier()
    if not notif.configured:
        return jsonify({
            "ok": False,
            "error": "Telegram belum dikonfigurasi.",
            "missing": notif.missing_config,
            "hint": "Jalankan: bash ~/Saham/setup_telegram.sh untuk setup wizard.",
        }), 400
    return jsonify(notif.send_test())


@app.route("/api/telegram/config", methods=["GET"])
def telegram_config():
    """Cek status konfigurasi Telegram TANPA expose token/secret."""
    notif = TelegramNotifier()
    return jsonify({
        "configured": notif.configured,
        "missing": notif.missing_config,
        "token_present": bool(notif.bot_token),
        "token_len": len(notif.bot_token) if notif.bot_token else 0,
        "chat_id_present": bool(notif.chat_id),
        "enabled_env": os.environ.get("TELEGRAM_ENABLED", "true"),
        "hint": ("Edit ~/Saham/.env: set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "
                 "TELEGRAM_ENABLED=true. Atau jalankan: bash ~/Saham/setup_telegram.sh"),
    })


@app.route("/api/telegram/diagnose", methods=["GET", "POST"])
def telegram_diagnose():
    """Full diagnostic: cek token via getMe, chat_id via getChat, kirim test message.
    Berguna untuk debug kalau "Telegram tidak masuk" — output kasih tahu persis
    mana yang salah (token, chat_id, atau bot belum di-/start).
    """
    notif = TelegramNotifier()
    out = {
        "step1_config": {
            "configured": notif.configured,
            "missing": notif.missing_config,
            "token_present": bool(notif.bot_token),
            "chat_id_present": bool(notif.chat_id),
        },
        "step2_validate_token": None,
        "step3_validate_chat": None,
        "step4_send_test": None,
        "verdict": None,
    }

    if not notif.bot_token:
        out["verdict"] = ("❌ TELEGRAM_BOT_TOKEN kosong. "
                          "Edit ~/Saham/.env atau jalankan setup_telegram.sh")
        return jsonify(out), 200

    # Step 2: validate token via getMe
    me = notif.get_me()
    out["step2_validate_token"] = me
    if not me.get("ok"):
        out["verdict"] = (f"❌ Token invalid: {me.get('error')}. "
                          "Cek ulang TELEGRAM_BOT_TOKEN dari @BotFather.")
        return jsonify(out), 200

    if not notif.chat_id:
        out["verdict"] = ("⚠️ Token OK, tapi TELEGRAM_CHAT_ID kosong. "
                          "Kirim /start ke bot Anda dulu, lalu buka URL: "
                          f"https://api.telegram.org/bot{notif.bot_token[:10]}.../"
                          "getUpdates — cari chat.id, isi ke .env.")
        return jsonify(out), 200

    # Step 3: validate chat_id via getChat
    chat = notif.get_chat()
    out["step3_validate_chat"] = chat
    if not chat.get("ok"):
        out["verdict"] = (f"❌ Chat ID invalid atau bot belum diizinkan: "
                          f"{chat.get('error')}. Buka Telegram, kirim /start ke "
                          "bot Anda, lalu coba lagi.")
        return jsonify(out), 200

    # Step 4: actually send test message
    test = notif.send_test()
    out["step4_send_test"] = test
    if test.get("ok"):
        bot_name = (me.get("bot") or {}).get("username", "?")
        chat_title = (chat.get("chat") or {}).get("title") or (chat.get("chat") or {}).get("first_name", "?")
        out["verdict"] = (f"✅ Telegram berfungsi! Bot @{bot_name} berhasil kirim "
                          f"test ke chat '{chat_title}'. Cek Telegram Anda.")
    else:
        out["verdict"] = (f"⚠️ Token & chat valid, tapi send_text gagal: "
                          f"{test.get('error') or test.get('result',{}).get('description')}")
    return jsonify(out), 200


@app.route("/api/telegram/send_dashboard", methods=["POST", "GET"])
def telegram_send_dashboard():
    """Kirim ringkasan Dashboard terstruktur (8 section) ke Telegram.

    Pengganti send_decisions yang lebih kaya: include market status, portfolio
    holdings, alokasi 4-bucket, action plan IDX+US dengan sizing, top 5 IDX+US,
    komoditas, alert. Cocok dipakai untuk morning brief.
    """
    notif = TelegramNotifier()
    if not notif.configured:
        return jsonify({
            "ok": False, "error": "Telegram belum dikonfigurasi.",
            "missing": notif.missing_config,
        }), 400

    # Fetch payload secara paralel-ish (via test_client = in-process)
    client = app.test_client()

    try:
        d_resp = client.get("/api/dashboard")
        dashboard = d_resp.get_json() if d_resp.status_code == 200 else {}
    except Exception as e:
        dashboard = {"error": str(e)}

    us_action_plan = None
    us_top5 = None
    try:
        ap_resp = client.get("/api/us/action_plan")
        if ap_resp.status_code == 200:
            us_action_plan = ap_resp.get_json()
    except Exception:
        pass
    try:
        t5_resp = client.get("/api/us/top5")
        if t5_resp.status_code == 200:
            us_top5 = (t5_resp.get_json() or {}).get("data")
    except Exception:
        pass

    result = notif.send_dashboard_summary(
        dashboard=dashboard, us_action_plan=us_action_plan, us_top5=us_top5
    )
    return jsonify(result)


@app.route("/api/telegram/send_decisions", methods=["POST"])
def telegram_send_decisions():
    """Kirim ringkasan rekomendasi hari ini ke Telegram."""
    notif = TelegramNotifier()
    if not notif.configured:
        return jsonify({"ok": False, "error": "Telegram belum dikonfigurasi"}), 400

    decisions = client_get_decisions()
    return jsonify(notif.send_decisions(decisions))


@app.route("/api/telegram/send_portfolio", methods=["POST"])
def telegram_send_portfolio():
    """Kirim ringkasan portfolio ke Telegram."""
    notif = TelegramNotifier()
    if not notif.configured:
        return jsonify({"ok": False, "error": "Telegram belum dikonfigurasi"}), 400

    c = app.test_client()
    portfolio = c.get("/api/portfolio").get_json() or []
    return jsonify(notif.send_portfolio_summary(portfolio))


@app.route("/api/telegram/status", methods=["GET"])
def telegram_status():
    notif = TelegramNotifier()
    return jsonify({
        "configured": notif.configured,
        "has_token": bool(notif.bot_token),
        "has_chat_id": bool(notif.chat_id),
    })


def client_get_decisions():
    """Helper internal."""
    c = app.test_client()
    return c.get("/api/decisions").get_json()


@app.route("/api/canslim/<ticker>", methods=["GET"])
def get_canslim(ticker):
    """Evaluasi CAN SLIM lengkap untuk 1 ticker (7 huruf)."""
    master_df = _load_master()
    info = _master_row(master_df, ticker)
    metrics = info.get("metrics", {})

    # Tambah data dari yfinance (52w high, vol spike, institusi) via cache
    hist = cache.get_history(ticker, period="1y", ttl_minutes=60)
    if hist is not None and not hist.empty:
        metrics["current_price"] = float(hist["Close"].iloc[-1])
        metrics["high_52w"] = float(hist["High"].max())
        if "Volume" in hist.columns and len(hist) > 11:
            today_vol = float(hist["Volume"].iloc[-1])
            avg_vol = float(hist["Volume"].iloc[-11:-1].mean())
            metrics["volume_spike"] = today_vol / avg_vol if avg_vol > 0 else None

    # Get info dari yfinance untuk institutional ownership
    ticker_info = cache.get_info(ticker, ttl_minutes=24 * 60)
    if ticker_info:
        metrics["held_percent_institutions"] = ticker_info.get("heldPercentInstitutions")

    metrics["free_float"] = info.get("free_float") if info else None

    # Ranking universe (untuk L)
    ranking = client_get_all_stocks()

    # IHSG status (untuk M)
    ihsg = get_ihsg_status(cache)

    result = evaluate_canslim(ticker.upper(), metrics, info.get("sector"),
                              ranking, market_status=ihsg)
    result["sector"] = info.get("sector")
    return jsonify(result)


def client_get_all_stocks():
    """Helper: ambil all stocks ranking via internal call."""
    c = app.test_client()
    resp = c.get("/api/all_stocks").get_json()
    return resp.get("stocks", []) if isinstance(resp, dict) else []


@app.route("/api/dsn_mui/<ticker>", methods=["GET"])
def get_dsn_mui(ticker):
    """Evaluasi DSN-MUI compliance untuk 1 ticker."""
    master_df = _load_master()
    info = _master_row(master_df, ticker)
    sector = info.get("sector")

    # Coba ambil totalDebt + totalAssets dari yfinance info
    ticker_info = cache.get_info(ticker, ttl_minutes=24 * 60) or {}
    total_debt = ticker_info.get("totalDebt")
    total_assets = ticker_info.get("totalAssets")
    industry = ticker_info.get("industry")

    result = evaluate_dsn_mui(
        ticker.upper(),
        sector=sector,
        industry=industry,
        total_debt=total_debt,
        total_assets=total_assets,
        non_halal_income_pct=None,  # belum bisa di-fetch otomatis
    )
    result["industry"] = industry
    return jsonify(result)


@app.route("/api/trading_mode", methods=["GET"])
def get_trading_mode():
    """Tampilkan mode trading aktif (swing / scalping / position)."""
    return jsonify(get_trading_config())


@app.route("/api/market", methods=["GET"])
def get_market():
    """Status IHSG (untuk filter CAN SLIM 'M')."""
    return jsonify(get_ihsg_status(cache))


@app.route("/api/tv/status", methods=["GET"])
def get_tv_status():
    """Diagnostik collector intraday TradingView (CDP hidup? umur cache? simbol?)."""
    try:
        from modules.tv_collector import status
        return jsonify({"success": True, **status()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/tv/poll", methods=["POST"])
def trigger_tv_poll():
    """Trigger manual satu siklus poll TradingView (force mengabaikan gate jam bursa)."""
    try:
        from modules.tv_collector import poll_and_store
        force = request.args.get("force", "0") == "1"
        return jsonify({"success": True, **poll_and_store(force=force)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/time/status", methods=["GET"])
def get_time_status():
    """Status sinkronisasi waktu nasional BMKG (WIB) + jendela koneksi saat ini."""
    out = {"success": True}
    try:
        from modules.time_sync import status as ts_status
        out["bmkg"] = ts_status()
    except Exception as e:
        out["bmkg_error"] = str(e)
    try:
        from modules.market_hours import is_connectivity_window, is_market_open, current_session_name
        out["connectivity_window"] = is_connectivity_window()
        out["market_open"] = is_market_open()
        out["session"] = current_session_name()
    except Exception as e:
        out["market_error"] = str(e)
    return jsonify(out)


@app.route("/api/ai/status", methods=["GET"])
def get_ai_status():
    """Diagnostik narasi AI (aktif? model? saham? kapan terakhir)."""
    try:
        from modules.ai_narrative import status
        return jsonify({"success": True, **status()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ai/generate", methods=["POST"])
def trigger_ai_narrative():
    """Trigger manual generate narasi AI (force mengabaikan gate jam bursa)."""
    try:
        from modules.ai_narrative import generate_and_store
        force = request.args.get("force", "0") == "1"
        return jsonify({"success": True, **generate_and_store(force=force)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/commodities", methods=["GET"])
def get_commodities():
    """Mengambil data komoditas terbaru dari scraper."""
    from modules.commodity_scraper import get_commodity_data
    force = request.args.get("refresh", "0") == "1"
    res = get_commodity_data(force_refresh=force)
    return jsonify(res)


@app.route("/api/gold/history", methods=["GET"])
def get_gold_history():
    """
    Mengambil riwayat harga Emas Antam 1 tahun terakhir.
    Menggunakan data hybrid: API logam-mulia-api untuk data aktual terbaru,
    dan yfinance (GC=F + USDIDR=X * 1.0828) untuk mengisi 1 tahun penuh harian.
    """
    cache_path = os.path.join(CACHE_DIR, "history", "GOLD_1Y.json")
    
    # TTL: 12 jam (720 menit)
    if os.path.exists(cache_path):
        age_min = (time.time() - os.path.getmtime(cache_path)) / 60
        if age_min < 720:
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
                
    # Fetch data fresh
    try:
        # 1. Fetch yfinance 1y history for GC=F and USDIDR=X
        gc_df = cache.get_history("GC=F", period="1y", ttl_minutes=720)
        usdidr_df = cache.get_history("USDIDR=X", period="1y", ttl_minutes=720)
        
        if gc_df is None or usdidr_df is None or gc_df.empty or usdidr_df.empty:
            raise ValueError("yfinance data not available")
            
        # Alignment data (Normalize timezone to avoid empty joins)
        gc_close_naive = gc_df["Close"].copy()
        usdidr_close_naive = usdidr_df["Close"].copy()
        
        gc_close_naive.index = pd.to_datetime(gc_close_naive.index, utc=True).tz_convert(None).normalize()
        usdidr_close_naive.index = pd.to_datetime(usdidr_close_naive.index, utc=True).tz_convert(None).normalize()
        
        # Gabungkan berdasarkan tanggal
        df_yf = pd.DataFrame(index=gc_close_naive.index)
        df_yf["GC"] = gc_close_naive
        df_yf = df_yf.join(usdidr_close_naive.to_frame("USDIDR"), how="inner")
        
        # Hitung harga emas IDR per gram dengan premium 1.0828
        df_yf["price"] = (df_yf["GC"] / 31.1034768) * df_yf["USDIDR"] * 1.0828
        
        # Buat list historical points
        history = []
        for idx, row in df_yf.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            history.append({
                "date": date_str,
                "price": round(float(row["price"]), 2)
            })
            
        # 2. Coba gabungkan/timpa dengan data aktual terbaru dari API logam-mulia-api
        try:
            api_url = "https://logam-mulia-api.iamutaki.workers.dev/api/prices/logammulia/history?length=365&weight=1"
            r = requests.get(api_url, timeout=5)
            if r.status_code == 200:
                api_data = r.json()
                if api_data.get("success") and api_data.get("data"):
                    # Map date -> price
                    api_prices = {}
                    for item in api_data["data"]:
                        if item.get("materialType") == "Emas Batangan":
                            d = item.get("recordedDate")
                            p = item.get("sellPrice")
                            if d and p:
                                api_prices[d] = float(p)
                                
                    # Timpa history yfinance dengan data API logam mulia yang persis
                    for point in history:
                        dt = point["date"]
                        if dt in api_prices:
                            point["price"] = api_prices[dt]
                            
                    # Tambahkan jika ada tanggal di API yang tidak ada di yfinance (misal akhir pekan)
                    existing_dates = set(p["date"] for p in history)
                    for dt, val in sorted(api_prices.items()):
                        if dt not in existing_dates:
                            history.append({"date": dt, "price": val})
        except Exception as e:
            print(f"[gold] Failed to merge with API logam mulia: {e}")
            
        # Sort by date
        history = sorted(history, key=lambda x: x["date"])
        
        # Simpan ke cache
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(history, f)
            
        return jsonify(history)
        
    except Exception as e:
        print(f"[gold] Failed to generate gold history: {e}")
        return jsonify([])


@app.route("/api/gold/prediction", methods=["GET"])
def get_gold_prediction():
    """
    Menghitung prediksi nilai jual & beli Emas per 100gram terbaik 1 hari atau 1 pekan kedepan.
    """
    from modules.commodity_scraper import get_commodity_data
    import re
    
    # 1. Ambil data komoditas saat ini (dari cache atau force refresh)
    force = request.args.get("refresh", "0") == "1"
    comm_data = get_commodity_data(force_refresh=force)
    
    # Ambil parameter horizon (1d = 1 hari, 1w = 1 pekan / 5 hari perdagangan)
    horizon = request.args.get("horizon", "1d")
    forecast_days = 5 if horizon == "1w" else 1
    
    # 2. Load riwayat harga dari cache /api/gold/history
    cache_path = os.path.join(CACHE_DIR, "history", "GOLD_1Y.json")
    
    history = []
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass
            
    # Tentukan baseline harga saat ini dari data histori terakhir
    if not history:
        return jsonify({"success": False, "error": "Data riwayat emas tidak tersedia"})
        
    last_actual_price = history[-1]["price"]
    last_date = history[-1]["date"]
    
    # 3. Forecast spot price (N=10 days regression slope + last price drift * forecast_days)
    N = 10
    if len(history) >= N:
        sub_hist = history[-N:]
    else:
        sub_hist = history
        N = len(history)
        
    prices = [point["price"] for point in sub_hist]
    x = list(range(N))
    sum_x = sum(x)
    sum_y = sum(prices)
    sum_xx = sum(xi**2 for xi in x)
    sum_xy = sum(xi*yi for xi, yi in zip(x, prices))
    
    denom = (N * sum_xx - sum_x**2)
    m = (N * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    
    # 3b. Call update_and_get_accuracy and apply feedback correction
    pred_type = "gold_1d" if horizon == "1d" else "gold_1w"
    avg_accuracy, bias_correction = update_and_get_accuracy(pred_type, history)
    
    # Project spot price per gram based on forecast horizon + bias correction
    predicted_gold_base_raw = last_actual_price + (m * forecast_days)
    predicted_gold_base = predicted_gold_base_raw + bias_correction
    
    # 4. Parse current 100g prices for Antam, Pegadaian from comm_data
    def parse_price(val_str):
        if not val_str:
            return 0.0
        cleaned = re.sub(r'[^\d]', '', str(val_str))
        return float(cleaned) if cleaned else 0.0
        
    antam_100g_sell = 0.0
    pegadaian_100g_sell = 0.0
    antam_buyback_gram = 0.0
    
    for row in comm_data.get("antam_pegadaian_table", []):
        if row.get("gram") == "100":
            antam_100g_sell = parse_price(row.get("antam"))
            pegadaian_100g_sell = parse_price(row.get("pegadaian"))
        elif row.get("gram") == "":
            antam_text = row.get("antam", "")
            match = re.search(r'pembelian kembali:\s*Rp([\d\.]+)', antam_text)
            if match:
                antam_buyback_gram = parse_price(match.group(1))
                
    # Fallback jika parsing mengembalikan 0
    if antam_100g_sell == 0: antam_100g_sell = 271512000.0
    if pegadaian_100g_sell == 0: pegadaian_100g_sell = 268768000.0
    
    # Estimasi Buyback
    antam_100g_buy = antam_buyback_gram * 100.0 if antam_buyback_gram > 0 else antam_100g_sell * 0.969
    pegadaian_100g_buy = pegadaian_100g_sell * 0.92
    
    # Base per 100g today
    current_gold_base_100g = last_actual_price * 100.0
    
    # Hitung rasio dan proyeksi besok
    agents = [
        {"name": "Antam (Butik Emas)", "sell": antam_100g_sell, "buy": antam_100g_buy},
        {"name": "Pegadaian (Antam)", "sell": pegadaian_100g_sell, "buy": pegadaian_100g_buy}
    ]
    
    projected_agents = []
    for agent in agents:
        sell_ratio = agent["sell"] / current_gold_base_100g if current_gold_base_100g > 0 else 1.0
        buy_ratio = agent["buy"] / current_gold_base_100g if current_gold_base_100g > 0 else 0.95
        
        pred_sell = predicted_gold_base * 100.0 * sell_ratio
        pred_buy = predicted_gold_base * 100.0 * buy_ratio
        
        projected_agents.append({
            "name": agent["name"],
            "current_sell": agent["sell"],
            "current_buy": agent["buy"],
            "predicted_sell": round(pred_sell, 2),
            "predicted_buy": round(pred_buy, 2),
            "change_sell_pct": round(((pred_sell - agent["sell"]) / agent["sell"] * 100), 4) if agent["sell"] > 0 else 0.0,
            "change_buy_pct": round(((pred_buy - agent["buy"]) / agent["buy"] * 100), 4) if agent["buy"] > 0 else 0.0
        })
        
    # Agen beli terbaik (harga jual terkecil)
    best_buy = min(projected_agents, key=lambda x: x["predicted_sell"])
    # Agen jual terbaik (harga beli/buyback terbesar)
    best_sell = max(projected_agents, key=lambda x: x["predicted_buy"])
    
    # Hitung trayektori 5 hari kerja (skipping weekends) untuk 1 pekan
    import datetime
    base_dt = datetime.datetime.strptime(last_date, "%Y-%m-%d")
    indo_days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    
    trajectory = []
    current_dt = base_dt
    for step in range(1, 6):
        while True:
            current_dt += datetime.timedelta(days=1)
            if current_dt.weekday() < 5: # Monday to Friday
                break
                
        # Apply scaled correction to trajectory step
        step_correction = bias_correction * (step / 5.0)
        pred_spot_raw = last_actual_price + (m * step)
        pred_spot = pred_spot_raw + step_correction
        
        day_agents = []
        for agent in agents:
            sell_ratio = agent["sell"] / current_gold_base_100g if current_gold_base_100g > 0 else 1.0
            buy_ratio = agent["buy"] / current_gold_base_100g if current_gold_base_100g > 0 else 0.95
            
            day_agents.append({
                "name": agent["name"],
                "sell": round(pred_spot * 100.0 * sell_ratio, 2),
                "buy": round(pred_spot * 100.0 * buy_ratio, 2)
            })
            
        b_buy = min(day_agents, key=lambda x: x["sell"])
        b_sell = max(day_agents, key=lambda x: x["buy"])
        
        trajectory.append({
            "step": step,
            "date": current_dt.strftime("%Y-%m-%d"),
            "day_name": indo_days[current_dt.weekday()],
            "predicted_spot_gram": round(pred_spot, 2),
            "best_buy_agent": {
                "name": b_buy["name"],
                "price": b_buy["sell"]
            },
            "best_sell_agent": {
                "name": b_sell["name"],
                "price": b_sell["buy"]
            }
        })
        
    best_buy_day = min(trajectory, key=lambda x: x["best_buy_agent"]["price"])
    best_sell_day = max(trajectory, key=lambda x: x["best_sell_agent"]["price"])
    
    std_dev = 0.0
    if len(prices) > 1:
        import numpy as np
        std_dev = float(np.std(prices))
        
    # Log today's prediction
    target_date = trajectory[-1]["date"] if horizon == "1w" else trajectory[0]["date"]
    log_prediction(pred_type, made_on=last_date, target_date=target_date, predicted_price=predicted_gold_base)
    
    return jsonify({
        "success": True,
        "date_today": last_date,
        "horizon": horizon,
        "forecast_days": forecast_days,
        "current_spot_gram": last_actual_price,
        "predicted_spot_gram": round(predicted_gold_base, 2),
        "daily_drift": round(m, 2),
        "agents": projected_agents,
        "best_buy_agent": {
            "name": best_buy["name"],
            "price": best_buy["predicted_sell"]
        },
        "best_sell_agent": {
            "name": best_sell["name"],
            "price": best_sell["predicted_buy"]
        },
        "weekly_trajectory": trajectory,
        "best_buy_day_info": {
            "date": best_buy_day["date"],
            "day_name": best_buy_day["day_name"],
            "agent": best_buy_day["best_buy_agent"]["name"],
            "price": best_buy_day["best_buy_agent"]["price"]
        },
        "best_sell_day_info": {
            "date": best_sell_day["date"],
            "day_name": best_sell_day["day_name"],
            "agent": best_sell_day["best_sell_agent"]["name"],
            "price": best_sell_day["best_sell_agent"]["price"]
        },
        "std_dev_10d": round(std_dev, 2),
        "accuracy_pct": avg_accuracy
    })


@app.route("/api/silver-dinar/prices", methods=["GET"])
def get_silver_dinar_prices():
    """
    Mengambil data harga Perak Spot & Perak Fisik Antam, serta Dinar KR real-time.
    """
    import re
    from bs4 import BeautifulSoup
    
    force = request.args.get("refresh", "0") == "1"
    
    silver_spot_usd = 30.5
    usdidr = 16100.0
    
    try:
        silver_df = cache.get_history("SI=F", period="5d", ttl_minutes=15, force_refresh=force)
        if silver_df is not None and not silver_df.empty:
            silver_spot_usd = float(silver_df["Close"].iloc[-1])
            
        usdidr_df = cache.get_history("USDIDR=X", period="5d", ttl_minutes=15, force_refresh=force)
        if usdidr_df is not None and not usdidr_df.empty:
            usdidr = float(usdidr_df["Close"].iloc[-1])
    except Exception as e:
        print(f"[silver-dinar] Failed to get silver spot/forex from yfinance: {e}")
        
    silver_spot_idr_gram = (silver_spot_usd / 31.1034768) * usdidr
    
    silver_spot_info = {
        "usd_per_oz": round(silver_spot_usd, 2),
        "idr_per_gram": round(silver_spot_idr_gram, 2)
    }
    
    silver_antam = [
        {"gram": "250", "price": round(250 * silver_spot_idr_gram * 1.15, 0)},
        {"gram": "500", "price": round(500 * silver_spot_idr_gram * 1.12, 0)},
        {"gram": "1000", "price": round(1000 * silver_spot_idr_gram * 1.09, 0)}
    ]
    
    dinar_cache_path = os.path.join(CACHE_DIR, "dinar_prices.json")
    dinar_prices = []
    dinar_date = ""
    dinar_scraped_ok = False
    
    if not force and os.path.exists(dinar_cache_path):
        age = time.time() - os.path.getmtime(dinar_cache_path)
        if age < 900:
            try:
                with open(dinar_cache_path, "r", encoding="utf-8") as f:
                    cached_d = json.load(f)
                    dinar_prices = cached_d.get("prices", [])
                    dinar_date = cached_d.get("date", "")
                    dinar_scraped_ok = True
            except Exception:
                pass
                
    if not dinar_scraped_ok:
        try:
            url_dinar = "https://dinarkr.com/main/harga-emas.php?action=dkrharga"
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url_dinar, headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                
                tgl_el = soup.select_one('.dkr-tgl')
                if tgl_el:
                    dinar_date = tgl_el.text.strip().replace("\n", " ").replace("  ", " ")
                else:
                    dinar_date = time.strftime("%d %b %Y %H.%M WIB")
                    
                tbody = soup.find('tbody')
                rows = tbody.find_all('tr') if tbody else []
                for i, row in enumerate(rows):
                    tds = row.find_all('td')
                    if len(tds) >= 3:
                        mapped_names = {
                            0: "1/8 Dinar",
                            1: "1/4 Dinar",
                            2: "1/2 Dinar",
                            3: "1 Dinar",
                            4: "2 Dinar",
                            5: "3 Dinar",
                            6: "4 Dinar",
                            7: "5 Dinar",
                            8: "7 Dinar",
                            9: "8 Dinar",
                            10: "10 Dinar"
                        }
                        name = mapped_names.get(i)
                        if not name:
                            img = tds[0].find('img')
                            name = img.get('alt', 'Dinar') if img else tds[0].text.strip()
                        
                        def clean_and_parse(val_str):
                            cleaned = re.sub(r'[^\d]', '', val_str)
                            return float(cleaned) if cleaned else 0.0
                            
                        konsumen = clean_and_parse(tds[1].text.strip())
                        buyback = clean_and_parse(tds[2].text.strip())
                        
                        if konsumen and buyback:
                            dinar_prices.append({
                                "name": name,
                                "sell": konsumen,
                                "buy": buyback
                            })
                            
                pde_items = soup.select('.pde')
                for item in pde_items:
                    h4 = item.find('h4')
                    name = h4.text.strip().replace("\n", " ").replace("  ", " ") if h4 else "Paket Dinar"
                    if not h4:
                        img = item.find('img')
                        if img and "20D" in img.get('src', ''):
                            name = "20 Dinar"
                    
                    harga_el = item.select_one('.harga')
                    buyback2_el = item.select_one('.buyback2')
                    
                    sell_val = 0.0
                    buy_val = 0.0
                    if harga_el:
                        sell_val = clean_and_parse(harga_el.text.strip())
                    if buyback2_el:
                        buy_val = clean_and_parse(buyback2_el.text.strip())
                    
                    if sell_val > 0:
                        dinar_prices.append({
                            "name": name,
                            "sell": sell_val,
                            "buy": buy_val
                        })
                
                if dinar_prices:
                    dinar_scraped_ok = True
                    os.makedirs(os.path.dirname(dinar_cache_path), exist_ok=True)
                    with open(dinar_cache_path, "w", encoding="utf-8") as f:
                        json.dump({"prices": dinar_prices, "date": dinar_date, "timestamp": time.time()}, f, indent=2)
        except Exception as e:
            print(f"[silver-dinar] Dinar scrape failed: {e}")
            
    if not dinar_prices:
        if os.path.exists(dinar_cache_path):
            try:
                with open(dinar_cache_path, "r", encoding="utf-8") as f:
                    cached_d = json.load(f)
                    dinar_prices = cached_d.get("prices", [])
                    dinar_date = cached_d.get("date", "")
            except Exception:
                pass
        
        if not dinar_prices:
            dinar_date = time.strftime("%d %b %Y %H.%M WIB") + " (Fallback)"
            dinar_prices = [
                {"name": "1/8 Dinar", "sell": 1814000.0, "buy": 1633000.0},
                {"name": "1/4 Dinar", "sell": 3501000.0, "buy": 3253000.0},
                {"name": "1/2 Dinar", "sell": 7011000.0, "buy": 6555000.0},
                {"name": "1 Dinar", "sell": 14041000.0, "buy": 13199000.0},
                {"name": "2 Dinar", "sell": 28044000.0, "buy": 26446000.0},
                {"name": "3 Dinar", "sell": 42075000.0, "buy": 39719000.0},
                {"name": "4 Dinar", "sell": 56057000.0, "buy": 52974000.0},
                {"name": "5 Dinar", "sell": 70110000.0, "buy": 66324000.0},
                {"name": "7 Dinar", "sell": 98164000.0, "buy": 92962000.0},
                {"name": "8 Dinar", "sell": 112171000.0, "buy": 106339000.0},
                {"name": "10 Dinar", "sell": 140192000.0, "buy": 133042000.0},
                {"name": "20 Dinar", "sell": 280242000.0, "buy": 266230000.0},
                {"name": "Paket Dinar Exclusive 1 Set", "sell": 224340000.0, "buy": 211723000.0},
                {"name": "Paket Dinar Luxury 1 Set", "sell": 462696000.0, "buy": 437727000.0}
            ]
            
    silver_spot_table = [
        {"unit": "Oz", "usd": f"${silver_spot_usd:.2f}", "idr": f"Rp {silver_spot_usd * usdidr:,.0f}"},
        {"unit": "Gram", "usd": f"${silver_spot_usd/31.1034768:.4f}", "idr": f"Rp {silver_spot_idr_gram:,.0f}"},
        {"unit": "Kg", "usd": f"${(silver_spot_usd/31.1034768)*1000:,.2f}", "idr": f"Rp {silver_spot_idr_gram*1000:,.0f}"}
    ]
    
    return jsonify({
        "success": True,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "silver_spot": silver_spot_info,
        "silver_spot_table": silver_spot_table,
        "silver_antam": silver_antam,
        "dinar_date": dinar_date,
        "dinar_prices": dinar_prices
    })


@app.route("/api/silver/history", methods=["GET"])
def get_silver_history():
    """
    Mengambil riwayat harga Perak Spot 1 tahun terakhir dalam IDR per gram.
    """
    cache_path = os.path.join(CACHE_DIR, "history", "SILVER_1Y.json")
    
    if os.path.exists(cache_path):
        age_min = (time.time() - os.path.getmtime(cache_path)) / 60
        if age_min < 720:
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
                
    try:
        si_df = cache.get_history("SI=F", period="1y", ttl_minutes=720)
        usdidr_df = cache.get_history("USDIDR=X", period="1y", ttl_minutes=720)
        
        if si_df is None or usdidr_df is None or si_df.empty or usdidr_df.empty:
            raise ValueError("yfinance data not available")
            
        si_close_naive = si_df["Close"].copy()
        usdidr_close_naive = usdidr_df["Close"].copy()
        
        si_close_naive.index = pd.to_datetime(si_close_naive.index, utc=True).tz_convert(None).normalize()
        usdidr_close_naive.index = pd.to_datetime(usdidr_close_naive.index, utc=True).tz_convert(None).normalize()
        
        df_yf = pd.DataFrame(index=si_close_naive.index)
        df_yf["SI"] = si_close_naive
        df_yf = df_yf.join(usdidr_close_naive.to_frame("USDIDR"), how="inner")
        
        df_yf["price"] = (df_yf["SI"] / 31.1034768) * df_yf["USDIDR"]
        
        history = []
        for idx, row in df_yf.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            history.append({
                "date": date_str,
                "price": round(float(row["price"]), 2)
            })
            
        history = sorted(history, key=lambda x: x["date"])
        
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(history, f)
            
        return jsonify(history)
    except Exception as e:
        print(f"[silver] Failed to generate silver history: {e}")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify([])


@app.route("/api/dinar/history", methods=["GET"])
def get_dinar_history():
    """
    Mengambil riwayat harga 1 Dinar KR 1 tahun terakhir.
    Mengekstrak array Highcharts dari dinarkr.com home page.
    """
    cache_path = os.path.join(CACHE_DIR, "history", "DINAR_1Y.json")
    
    if os.path.exists(cache_path):
        age_min = (time.time() - os.path.getmtime(cache_path)) / 60
        if age_min < 720:
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
                
    try:
        import datetime
        import re
        r = requests.get("https://dinarkr.com/", timeout=10)
        if r.status_code == 200:
            match = re.search(r'var\s+data\s*=\s*(\[\[.*?\]\])', r.text)
            if match:
                raw_data = json.loads(match.group(1))
                history = []
                for item in raw_data:
                    ts = item[0] / 1000.0
                    val = float(item[1]) * 4.0
                    dt_str = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                    history.append({"date": dt_str, "price": val})
                
                history = sorted(history, key=lambda x: x["date"])
                
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(history, f)
                    
                return jsonify(history)
            else:
                raise ValueError("var data array not found in HTML")
        else:
            raise ValueError(f"HTTP Status {r.status_code}")
    except Exception as e:
        print(f"[dinar] Failed to generate dinar history: {e}")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception:
                pass
        return jsonify([])


@app.route("/api/dinar/prediction", methods=["GET"])
def get_dinar_prediction():
    """
    Menghitung prediksi nilai jual & beli koin 10 Dinar KR terbaik 1 hari atau 1 pekan kedepan.
    """
    import re
    import datetime
    
    force = request.args.get("refresh", "0") == "1"
    
    try:
        url_prices = f"http://127.0.0.1:8000/api/silver-dinar/prices"
        if force:
            url_prices += "?refresh=1"
        requests.get(url_prices, timeout=5)
    except Exception:
        pass
        
    dinar_cache_path = os.path.join(CACHE_DIR, "dinar_prices.json")
    dinar_prices = []
    if os.path.exists(dinar_cache_path):
        try:
            with open(dinar_cache_path, "r", encoding="utf-8") as f:
                dinar_prices = json.load(f).get("prices", [])
        except Exception:
            pass
            
    horizon = request.args.get("horizon", "1d")
    forecast_days = 5 if horizon == "1w" else 1
    
    cache_path = os.path.join(CACHE_DIR, "history", "DINAR_1Y.json")
    history = []
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass
            
    if not history:
        try:
            from flask import current_app
            with current_app.test_client() as client:
                history = client.get("/api/dinar/history").get_json() or []
        except Exception:
            pass
            
    if not history:
        return jsonify({"success": False, "error": "Data riwayat Dinar tidak tersedia"})
        
    last_actual_price = history[-1]["price"]
    last_date = history[-1]["date"]
    
    N = 10
    if len(history) >= N:
        sub_hist = history[-N:]
    else:
        sub_hist = history
        N = len(history)
        
    prices = [point["price"] for point in sub_hist]
    x = list(range(N))
    sum_x = sum(x)
    sum_y = sum(prices)
    sum_xx = sum(xi**2 for xi in x)
    sum_xy = sum(xi*yi for xi, yi in zip(x, prices))
    
    denom = (N * sum_xx - sum_x**2)
    m = (N * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0.0
    
    # 3b. Call update_and_get_accuracy and apply feedback correction
    pred_type = "dinar_1d" if horizon == "1d" else "dinar_1w"
    avg_accuracy, bias_correction = update_and_get_accuracy(pred_type, history)
    
    # Apply bias correction (1 Dinar base)
    predicted_dinar_base_raw = last_actual_price + (m * forecast_days)
    predicted_dinar_base = predicted_dinar_base_raw + bias_correction
    
    current_10d_sell = 0.0
    current_10d_buy = 0.0
    current_1d_sell = 0.0
    current_1d_buy = 0.0
    
    for row in dinar_prices:
        if row.get("name") == "10 Dinar":
            current_10d_sell = float(row.get("sell", 0.0))
            current_10d_buy = float(row.get("buy", 0.0))
        elif row.get("name") == "1 Dinar":
            current_1d_sell = float(row.get("sell", 0.0))
            current_1d_buy = float(row.get("buy", 0.0))
            
    if current_10d_sell == 0.0:
        current_10d_sell = current_1d_sell * 10.0 if current_1d_sell > 0.0 else last_actual_price * 10.0
    if current_10d_buy == 0.0:
        current_10d_buy = current_1d_buy * 10.0 if current_1d_buy > 0.0 else last_actual_price * 10.0 * 0.94
        
    current_10d_base = last_actual_price * 10.0
    sell_ratio = current_10d_sell / current_10d_base if current_10d_base > 0 else 1.0
    buy_ratio = current_10d_buy / current_10d_base if current_10d_base > 0 else 0.94
    
    pred_sell = predicted_dinar_base * 10.0 * sell_ratio
    pred_buy = predicted_dinar_base * 10.0 * buy_ratio
    
    change_sell_pct = ((pred_sell - current_10d_sell) / current_10d_sell * 100) if current_10d_sell > 0 else 0.0
    change_buy_pct = ((pred_buy - current_10d_buy) / current_10d_buy * 100) if current_10d_buy > 0 else 0.0
    
    base_dt = datetime.datetime.strptime(last_date, "%Y-%m-%d")
    indo_days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    
    trajectory = []
    current_dt = base_dt
    for step in range(1, 6):
        while True:
            current_dt += datetime.timedelta(days=1)
            if current_dt.weekday() < 5:
                break
                
        # Apply scaled correction to trajectory step
        step_correction = bias_correction * (step / 5.0)
        pred_spot_step_raw = last_actual_price + (m * step)
        pred_spot_step = pred_spot_step_raw + step_correction
        
        p_sell = pred_spot_step * 10.0 * sell_ratio
        p_buy = pred_spot_step * 10.0 * buy_ratio
        
        trajectory.append({
            "step": step,
            "date": current_dt.strftime("%Y-%m-%d"),
            "day_name": indo_days[current_dt.weekday()],
            "predicted_sell": round(p_sell, 2),
            "predicted_buy": round(p_buy, 2)
        })
        
    best_buy_day = min(trajectory, key=lambda x: x["predicted_sell"])
    best_sell_day = max(trajectory, key=lambda x: x["predicted_buy"])
    
    std_dev = 0.0
    if len(prices) > 1:
        import numpy as np
        std_dev = float(np.std(prices))
        
    # Log today's prediction
    target_date = trajectory[-1]["date"] if horizon == "1w" else trajectory[0]["date"]
    log_prediction(pred_type, made_on=last_date, target_date=target_date, predicted_price=predicted_dinar_base)
    
    return jsonify({
        "success": True,
        "date_today": last_date,
        "horizon": horizon,
        "forecast_days": forecast_days,
        "current_10d_sell": current_10d_sell,
        "current_10d_buy": current_10d_buy,
        "predicted_10d_sell": round(pred_sell, 2),
        "predicted_10d_buy": round(pred_buy, 2),
        "change_sell_pct": round(change_sell_pct, 4),
        "change_buy_pct": round(change_buy_pct, 4),
        "daily_drift": round(m * 10.0, 2),
        "best_buy_day_info": {
            "date": best_buy_day["date"],
            "day_name": best_buy_day["day_name"],
            "price": best_buy_day["predicted_sell"]
        },
        "best_sell_day_info": {
            "date": best_sell_day["date"],
            "day_name": best_sell_day["day_name"],
            "price": best_sell_day["predicted_buy"]
        },
        "weekly_trajectory": trajectory,
        "std_dev_10d": round(std_dev * 10.0, 2),
        "accuracy_pct": avg_accuracy
    })


def generate_metric_narratives(ticker, sector, metrics, tech):
    narratives = {}
    
    # 1. EPS Growth
    eps_g = metrics.get("eps_growth")
    if eps_g and eps_g != "N/A":
        try:
            val = float(eps_g.replace("%", "").replace(",", "").strip())
            if val > 25:
                narratives["eps_growth"] = f"Laba bersih tumbuh sangat pesat sebesar {eps_g}. Ini menunjukkan ekspansi bisnis dan permintaan produk/jasa perusahaan berkembang pesat."
            elif val > 0:
                narratives["eps_growth"] = f"Laba bersih tumbuh sehat sebesar {eps_g}. Kinerja operasional perusahaan berjalan stabil dan menguntungkan."
            else:
                narratives["eps_growth"] = f"Laba bersih menyusut {eps_g} dibanding kuartal yang sama tahun lalu. Perlu diperhatikan langkah efisiensi atau faktor musiman industri."
        except:
            narratives["eps_growth"] = f"Pertumbuhan laba bersih tercatat sebesar {eps_g}."
    else:
        narratives["eps_growth"] = "Data pertumbuhan laba belum terlaporkan atau tidak tersedia."

    # 2. ROE (Return on Equity)
    roe = metrics.get("roe")
    if roe and roe != "N/A":
        try:
            val = float(roe.replace("%", "").replace(",", "").strip())
            if val >= 15:
                narratives["roe"] = f"Sangat efisien! Pengembalian modal pemegang saham mencapai {roe} (di atas target aman 15%). Menandakan manajemen sangat produktif memutarkan modal."
            elif val > 0:
                narratives["roe"] = f"Perusahaan menghasilkan keuntungan sebesar {roe} dari modalnya, namun kinerjanya masih di bawah batas ideal 15%."
            else:
                narratives["roe"] = f"Pengembalian modal negatif ({roe}). Perusahaan mengalami kerugian operasional dan perlu memulihkan efisiensinya."
        except:
            narratives["roe"] = f"Rasio pengembalian modal (ROE) sebesar {roe}."
    else:
        narratives["roe"] = "Data efisiensi modal tidak tersedia."

    # 3. DER (Debt to Equity Ratio)
    der = metrics.get("der")
    if der and der != "N/A":
        try:
            val = float(der.replace("%", "").replace(",", "").strip())
            if val < 50:
                narratives["der"] = f"Sangat aman! Utang sangat rendah, hanya {der} dari total modal. Risiko keuangan/kebangkrutan sangat minim."
            elif val < 100:
                narratives["der"] = f"Kadar utang terkontrol dengan baik sebesar {der} (di bawah batas psikologis 100%), aman dari risiko gagal bayar."
            else:
                narratives["der"] = f"Utang cukup tinggi ({der} dari modal). Perusahaan perlu waspada mengelola beban bunga jika suku bunga naik."
        except:
            narratives["der"] = f"Rasio utang terhadap modal (DER) sebesar {der}."
    else:
        narratives["der"] = "Data tingkat utang tidak tersedia."

    # 4. PBV (Price to Book Value)
    pbv = metrics.get("pbv")
    if pbv and pbv != "N/A":
        try:
            val = float(pbv.replace("x", "").replace(",", "").strip())
            if val < 1.0:
                narratives["pbv"] = f"Sangat murah (Undervalue)! Harga saham dihargai {pbv} dari nilai buku aset bersihnya (terdapat diskon besar)."
            elif val < 2.0:
                narratives["pbv"] = f"Valuasi wajar! Harga saham bernilai {pbv} dari nilai bukunya, harga yang adil bagi investor."
            else:
                narratives["pbv"] = f"Valuasi premium! Saham dihargai {pbv} dari nilai aset bersihnya karena ekspektasi pasar yang tinggi terhadap masa depan emiten."
        except:
            narratives["pbv"] = f"Rasio PBV tercatat sebesar {pbv}."
    else:
        narratives["pbv"] = "Data valuasi nilai buku tidak tersedia."

    # 5. RSI (14)
    rsi_val = tech.get("rsi")
    if rsi_val is not None:
        try:
            val = float(rsi_val)
            if val < 30:
                narratives["rsi"] = f"Sudah terlalu murah / jenuh jual (RSI: {val:.1f}). Tekanan jual berkurang drastis, berpeluang kuat untuk rebound/balik arah naik."
            elif val > 70:
                narratives["rsi"] = f"Sudah cukup mahal / jenuh beli (RSI: {val:.1f}). Waspada potensi aksi ambil untung (profit taking) jangka pendek."
            else:
                narratives["rsi"] = f"Harga bergerak stabil di area netral (RSI: {val:.1f}), tidak terlalu murah dan tidak terlalu mahal."
        except:
            narratives["rsi"] = f"Indikator RSI tercatat sebesar {rsi_val}."
    else:
        narratives["rsi"] = "Data momentum RSI tidak tersedia."

    # 6. MA Crossover
    ma_cross = tech.get("ma_cross")
    if ma_cross == "GOLDEN":
        narratives["ma_cross"] = "Tren pergerakan harga jangka menengah terkonfirmasi naik (Golden Cross MA20 > MA50), awal momentum tren naik."
    elif ma_cross == "DEATH":
        narratives["ma_cross"] = "Tren pergerakan harga cenderung melemah/koreksi (Death Cross MA20 < MA50), sebaiknya wait and see."
    else:
        narratives["ma_cross"] = "Pergerakan harga saat ini konsolidasi datar (sideways)."

    # Sector specific narrative
    sec_lower = (sector or "").lower()
    if "health" in sec_lower:
        narratives["sector_note"] = "Sektor Kesehatan memiliki karakteristik defensif (produknya selalu dicari). Kestabilan pendapatan, profitabilitas ROE tinggi, dan utang rendah menjadi keunggulan utama saham ini."
        # Adjust PBV narrative if ROE is high in healthcare
        try:
            val_pbv = float(pbv.replace("x", "").replace(",", "").strip())
            val_roe = float(roe.replace("%", "").replace(",", "").strip())
            if val_pbv >= 2.0 and val_roe >= 15:
                narratives["pbv"] = f"Valuasi premium ({pbv}) sangat wajar untuk emiten kesehatan dengan ROE unggul ({roe}), karena pasar menyukai arus kas defensif."
        except:
            pass
    elif "consumer cyclical" in sec_lower:
        narratives["sector_note"] = "Sektor Barang Konsumen Siklikal sangat bergantung pada daya beli konsumen dan siklus ekonomi. Pertumbuhan laba yang melesat menunjukkan daya saing produk yang kuat di pasar."
    elif "basic materials" in sec_lower:
        narratives["sector_note"] = "Sektor Bahan Baku Industri sensitif terhadap harga komoditas dan industri konstruksi. DER yang rendah merupakan tameng kuat untuk bertahan di siklus industri lambat."
    elif "communication" in sec_lower or "technology" in sec_lower:
        narratives["sector_note"] = "Sektor Teknologi & Komunikasi mengutamakan pertumbuhan skala dan inovasi. PBV rendah dipadukan dengan momentum naik menjadi peluang investasi bernilai tinggi."
    elif "consumer defensive" in sec_lower:
        narratives["sector_note"] = "Sektor Barang Konsumen Primer (Defensif) tahan terhadap resesi karena menjual kebutuhan pokok harian. Karakter utama saham ini adalah pertumbuhan stabil dan risiko rendah."
    else:
        narratives["sector_note"] = f"Sektor {sector} memiliki dinamika industri tersendiri. Keseimbangan antara fundamental sehat dan momentum tren harga naik memberikan landasan investasi yang solid."

    return narratives


@app.route("/api/top5_recommendations", methods=["GET"])
@memoize_json(ttl_seconds=20)
def get_top5_recommendations():
    """
    Saring & rank top 5 Saham Syariah berdasarkan kombinasi skor fundamental,
    tren teknikal, dan prioritas keputusan eksekusi hari ini (korelasi positif).
    """
    stocks = client_get_all_stocks()
    if not stocks:
        return jsonify([])

    # Ambil keputusan hari ini untuk menghitung korelasi positif bonus eksekusi
    decisions = client_get_decisions() or {}
    buy_decisions = {d["ticker"]: d for d in decisions.get("buy", [])}
    sell_decisions = {d["ticker"]: d for d in decisions.get("sell", [])}
    hold_decisions = {d["ticker"]: d for d in decisions.get("hold", [])}

    valid_candidates = []
    for s in stocks:
        ticker = s.get("ticker")
        price = s.get("current_price") or 0.0
        fund_label = s.get("fundamental_label") or "AVOID"
        
        # Saring emiten tanpa data harga atau berstatus AVOID secara fundamental
        if price <= 0 or fund_label == "AVOID":
            continue

        fund_score = s.get("fundamental_score") or 0
        tech_score = s.get("technical_score") or 0

        # Hitung bonus keputusan harian agar ada korelasi positif kuat dengan Rekomendasi Hari Ini
        decision_bonus = 0
        if ticker in buy_decisions:
            dec = buy_decisions[ticker]
            urgency = dec.get("urgency", "MEDIUM")
            confidence = dec.get("confidence", "MEDIUM")
            if urgency == "HIGH" and confidence == "HIGH":
                decision_bonus = 10  # Sinyal beli terkuat hari ini (Strong Setup / Jalur 7% breakout)
            elif confidence == "HIGH":
                decision_bonus = 7
            elif confidence == "MEDIUM":
                decision_bonus = 4
            else:
                decision_bonus = 2
        elif ticker in sell_decisions:
            # Penalti berat agar saham yang harus dijual hari ini tidak masuk ke Top 5 Pilihan Beli
            decision_bonus = -30
        elif ticker in hold_decisions:
            # Berikan sedikit bonus untuk saham portofolio yang sedang di-hold (kualitas terbukti)
            decision_bonus = 1

        # Bobot formula: 2 * fundamental + technical + decision_bonus
        combined_rank_score = (fund_score * 2) + tech_score + decision_bonus
        
        # Buat salinan emiten dengan skor gabungan
        candidate = s.copy()
        candidate["combined_rank_score"] = combined_rank_score
        valid_candidates.append(candidate)

    # Urutkan berdasarkan combined_rank_score descending, lalu fundamental_score, lalu technical_score
    valid_candidates.sort(
        key=lambda x: (
            x["combined_rank_score"],
            x["fundamental_score"],
            x["technical_score"]
        ),
        reverse=True
    )

    # Ambil 5 teratas
    top5 = valid_candidates[:5]

    # Mapping final_signal dari istilah trading (BUY/SELL) ke istilah penilaian investasi (Rating)
    signal_mapping = {
        "STRONG BUY": "SANGAT LAYAK (Top Pick)",
        "BUY": "LAYAK INVESTASI",
        "ACCUMULATE": "CICIL AKUMULASI",
        "SPECULATIVE BUY": "SPEKULATIF",
        "WATCH (Tech Weak)": "PANTAU (Konsolidasi)",
        "HOLD": "WAIT & SEE",
        "AVOID": "HINDARI"
    }

    # Generate narasi analisis parameter & lakukan pemetaan istilah
    for item in top5:
        # Peta istilah final_signal
        orig_sig = item.get("final_signal", "HOLD")
        item["final_signal"] = signal_mapping.get(orig_sig, orig_sig)

        item["narratives"] = generate_metric_narratives(
            ticker=item["ticker"],
            sector=item["sector"],
            metrics={
                "eps_growth": item.get("eps_growth"),
                "roe": item.get("roe"),
                "der": item.get("der"),
                "pbv": item.get("pbv")
            },
            tech={
                "rsi": item.get("rsi"),
                "ma_cross": item.get("ma_cross")
            }
        )

    return jsonify(top5)



@app.route("/api/position_size", methods=["POST"])
def position_size():
    """
    Hitung position sizing Taichi-style.
    Body: {"idle_money": float, "n_stocks": int, "market_price": float, "profile": str}
    """
    data = request.json or {}
    try:
        idle = float(data.get("idle_money", 0))
        n = int(data.get("n_stocks", 1))
        mp = float(data.get("market_price", 0))
        profile = data.get("profile", "moderat")
    except (TypeError, ValueError):
        return jsonify({"error": "Input tidak valid"}), 400

    return jsonify(calc_position_size(idle, n, mp, profile))


@app.route("/api/calc_average", methods=["POST"])
def calc_avg_endpoint():
    """Hitung harga rata-rata setelah multi-entry."""
    data = request.json or {}
    return jsonify(calc_average(data.get("entries", [])))


@app.route("/api/decisions", methods=["GET"])
@memoize_json(ttl_seconds=20)
def get_decisions():
    """
    REKOMENDASI FINAL — gabungan portfolio + ranking + prospects.
    Output: list aksi BUY/SELL terprioritas + verdict global hari ini.
    """
    client = app.test_client()
    portfolio = client.get("/api/portfolio").get_json() or []
    ranking_resp = client.get("/api/all_stocks").get_json()
    ranking = ranking_resp.get("stocks", []) if isinstance(ranking_resp, dict) else []
    prospects = client.get("/api/prospects").get_json() or []

    # Ambil Saldo Kas RDN dan pemetaan kepemilikan broker
    broker_cash = {"Bibit": 0.0, "Pluang": 0.0, "Profit Anywhere": 0.0}
    broker_holdings_map = {}
    try:
        broker_port = client.get("/api/broker_portfolio").get_json() or {}
        platforms = broker_port.get("summary", {}).get("platforms", {})
        for plat in broker_cash:
            if plat in platforms:
                broker_cash[plat] = float(platforms[plat].get("cash", 0.0))
        
        # Peta ticker -> platform
        holdings_list = broker_port.get("holdings", [])
        for h in holdings_list:
            t = h.get("ticker")
            p_name = h.get("platform")
            if t and p_name:
                broker_holdings_map[t] = p_name
    except Exception as e:
        print(f"[api/decisions] Gagal mengambil data portfolio broker: {e}")

    market_status = get_ihsg_status(cache)
    step_info = load_18langkah_current_step()
    return jsonify(build_decisions(portfolio, ranking, prospects,
                                    market_status=market_status,
                                    broker_cash=broker_cash,
                                    broker_holdings_map=broker_holdings_map,
                                    step_info=step_info))


@app.route("/api/export/<fmt>", methods=["POST", "GET"])
def export_report(fmt):
    """Export laporan ke xlsx atau pdf."""
    from flask import send_file
    fmt = fmt.lower()
    if fmt not in ("xlsx", "pdf"):
        return jsonify({"error": "format harus xlsx atau pdf"}), 400

    client = app.test_client()
    ranking = client.get("/api/all_stocks").get_json().get("stocks", [])
    portfolio = client.get("/api/portfolio").get_json()
    alerts_today = client.get("/api/alerts/today").get_json()

    summary = build_summary(ranking, portfolio, alerts_today)

    if fmt == "xlsx":
        path = export_xlsx(ranking, portfolio, alerts_today, summary)
    else:
        path = export_pdf(ranking, portfolio, alerts_today, summary)

    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))


@app.route("/api/alerts/scan", methods=["POST", "GET"])
def alerts_scan():
    """Jalankan alert scan manual. Return list alert terdeteksi."""
    result = run_alert_scan(app_test_client=app.test_client())
    return jsonify(result)


@app.route("/api/alerts/today", methods=["GET"])
def alerts_today():
    """Return alert yang sudah ditulis hari ini."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = os.path.join(BASE_DIR, "logs", "alerts", f"{today}.json")
    if not os.path.exists(daily_file):
        return jsonify([])
    import json
    with open(daily_file, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/cache/stats", methods=["GET"])
def cache_stats():
    return jsonify(cache.stats())


@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    cache.clear()
    return jsonify({"success": True})


# =================== PEGADAIAN (Emas Digital Tring) =================== #
def _pegadaian_current_price() -> float:
    """Ambil harga emas Pegadaian per gram dari commodity scraper cache.
    Fallback: 2.6 juta/gram (estimasi konservatif)."""
    try:
        from modules.commodity_scraper import get_commodity_data
        cd = get_commodity_data()
        px = pgd.parse_pegadaian_price_per_gram(cd)
        if px and px > 0:
            return float(px)
    except Exception as e:
        print(f"[pegadaian] fetch current price failed: {e}")
    return 2_600_000.0


@app.route("/api/pegadaian/current_price", methods=["GET"])
def pegadaian_current_price():
    """Harga emas Pegadaian per gram (untuk pre-fill form transaksi)."""
    price = _pegadaian_current_price()
    return jsonify({"price_per_gram": price, "source": "harga-emas.org → Pegadaian Antam"})


@app.route("/api/pegadaian/transactions", methods=["GET"])
def pegadaian_transactions_list():
    """List semua transaksi Pegadaian, terbaru di atas."""
    txs = pgd.load_transactions(PEGADAIAN_FILE)
    return jsonify(txs)


@app.route("/api/pegadaian/transactions", methods=["POST"])
def pegadaian_transactions_add():
    """Tambah transaksi Pegadaian (BUY/SELL/TOPUP/WITHDRAWAL)."""
    data = request.get_json(force=True, silent=True) or {}
    result = pgd.add_transaction(PEGADAIAN_FILE, data)
    if "error" in result:
        return jsonify({"success": False, "error": result["error"]}), 400
    return jsonify({"success": True, "transaction": result})


@app.route("/api/pegadaian/transactions/<tx_id>", methods=["DELETE"])
def pegadaian_transactions_delete(tx_id):
    """Hapus transaksi by id."""
    ok = pgd.delete_transaction(PEGADAIAN_FILE, tx_id)
    if not ok:
        return jsonify({"success": False, "error": "Transaksi tidak ditemukan"}), 404
    return jsonify({"success": True})


@app.route("/api/pegadaian/portfolio", methods=["GET"])
def pegadaian_portfolio():
    """Ringkasan portofolio Pegadaian: total gram, P/L, saldo Rp."""
    current_price = _pegadaian_current_price()
    summary = pgd.summarize(PEGADAIAN_FILE, current_price_per_gram=current_price)
    summary["transactions"] = pgd.load_transactions(PEGADAIAN_FILE)
    return jsonify(summary)


# =================== GLOBAL FACTOR (Layer 1) =================== #
@app.route("/api/global_factor", methods=["GET"])
def get_global_factor():
    """
    Composite Global Risk Factor (US market sebagai leading indicator IHSG).

    Indikator: S&P500 (^GSPC), Nasdaq (^IXIC), VIX (^VIX), DXY (DX-Y.NYB),
    US10Y (^TNX). Output: status RISK_ON / NEUTRAL / RISK_OFF + score 0..100 +
    influence_multiplier untuk threshold trading.
    """
    try:
        result = compute_global_factor(cache_obj=cache)
        return jsonify(result)
    except Exception as e:
        log.warning("global_factor failed: %s", e)
        return jsonify({
            "status": "NEUTRAL",
            "score": 50.0,
            "influence_multiplier": 1.0,
            "narrative": f"Fallback NEUTRAL (fetch error: {e})",
            "errors": [str(e)],
            "components": {},
        }), 200


# =================== DASHBOARD GABUNGAN =================== #
@app.route("/api/dashboard", methods=["GET"])
def get_dashboard():
    """
    Endpoint agregat untuk halaman utama Dashboard Trading Syariah.

    Menggabungkan: status IHSG + ringkasan portfolio + alokasi target
    (saham/emas/cash) + action plan harian + top 5 saham + sinyal komoditas
    + alert aktif. Satu round-trip untuk halaman dashboard.
    """
    from datetime import datetime
    import json as _json

    client = app.test_client()
    out = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "ihsg": None,
        "global_factor": None,
        "portfolio": None,
        "allocation": None,
        "action_plan": None,
        "top5": [],
        "commodities": None,
        "alerts": [],
        "rotation_advisor": None,
    }

    # ---- IHSG status ----
    try:
        out["ihsg"] = get_ihsg_status(cache)
    except Exception as e:
        out["ihsg"] = {"error": str(e)}

    # ---- Global Factor (Layer 1: US market as leading indicator) ----
    try:
        out["global_factor"] = compute_global_factor(cache_obj=cache)
    except Exception as e:
        log.warning("global_factor failed: %s", e)
        out["global_factor"] = {
            "status": "NEUTRAL", "score": 50.0, "influence_multiplier": 1.0,
            "narrative": f"Fallback NEUTRAL ({e})", "components": {}, "errors": [str(e)],
        }

    # ---- SINGLE SOURCE OF TRUTH: panggil aggregator ----
    # Aggregator gabungkan broker_transactions.csv + portfolio.csv + pegadaian_transactions.csv
    # → semua endpoint (dashboard, broker_portfolio, portfolio) pakai angka yang SAMA.
    canonical = get_canonical_assets()
    portfolio_items = []  # untuk kompat dengan /api/portfolio yang lama (dipakai sizing)

    # Build portfolio_items dari aggregator holdings
    for h in canonical.get("holdings", []):
        portfolio_items.append({
            "ticker": h["ticker"],
            "harga_beli": h["avg_price"],
            "lot": h["lot"],
            "sekarang": h["current_price"],
            "pnl": h["pnl_pct"],
            "platform": h["platform"],
        })

    portfolio_value_rp = float(canonical.get("breakdown", {}).get("stocks_rp") or 0)
    broker_cash_rp = float(canonical.get("breakdown", {}).get("cash_rp") or 0)
    # Pisahkan: cash murni broker vs pegadaian cash & emas
    pegadaian_summary = (canonical.get("platforms", {}).get("Pegadaian") or {})
    pegadaian_emas_value_rp = float(pegadaian_summary.get("gold_value") or 0)
    pegadaian_cash_rp = float(pegadaian_summary.get("cash") or 0)
    # broker_cash di aggregator sudah INCLUDE pegadaian cash, kurangi supaya tidak double
    broker_cash_only_rp = broker_cash_rp - pegadaian_cash_rp

    # Total invested & realized P/L dari aggregator (lebih akurat dari hitung manual)
    portfolio_invested_rp = float(canonical.get("total_invested_rp") or 0)
    pnl_today_rp = float(canonical.get("total_unrealized_pnl_rp") or 0)

    pnl_today_pct = (pnl_today_rp / portfolio_invested_rp * 100) if portfolio_invested_rp > 0 else 0.0
    # SEMUA NILAI dari aggregator (canonical source of truth)
    out["portfolio"] = {
        "n_holdings": len(portfolio_items),
        "value_rp": round(portfolio_value_rp, 0),
        "invested_rp": round(portfolio_invested_rp, 0),
        "cash_rp": round(broker_cash_only_rp, 0),
        "pegadaian_cash_rp": round(pegadaian_cash_rp, 0),
        "pegadaian_emas_rp": round(pegadaian_emas_value_rp, 0),
        "pegadaian_gram": pegadaian_summary.get("gold_gram", 0),
        # ← total dari aggregator (canonical) — IDENTIK dengan Tab Portofolio
        "total_rp": round(float(canonical.get("total_asset_rp") or 0), 0),
        "pnl_rp": round(pnl_today_rp, 0),
        "pnl_pct": round(pnl_today_pct, 2),
        "holdings": portfolio_items,
        "platforms": canonical.get("platforms", {}),
        "warnings": canonical.get("warnings", []),
    }

    # ---- Action plan (decisions dari decision.py) ----
    decisions = {}
    try:
        r = client.get("/api/decisions")
        if r.status_code == 200:
            decisions = r.get_json() or {}
        # Compact action plan: ambil top URGENT/HIGH dari sell + top HIGH dari buy
        sell_list = decisions.get("sell", []) or []
        buy_list = decisions.get("buy", []) or []
        urgent_sell = [d for d in sell_list if d.get("urgency") in ("URGENT", "HIGH")][:3]
        top_buy = [d for d in buy_list if d.get("confidence") == "HIGH"][:3]
        out["action_plan"] = {
            "verdict": (decisions.get("summary") or {}).get("verdict"),
            "n_buy":  (decisions.get("summary") or {}).get("n_buy", 0),
            "n_sell": (decisions.get("summary") or {}).get("n_sell", 0),
            "n_hold": (decisions.get("summary") or {}).get("n_hold", 0),
            "top_actions": urgent_sell + top_buy,
            "all_sell": sell_list[:5],
            "all_buy":  buy_list[:5],
        }
    except Exception as e:
        out["action_plan"] = {"error": str(e)}

    # ---- Top 5 saham ----
    try:
        r = client.get("/api/top5_recommendations")
        if r.status_code == 200:
            out["top5"] = r.get_json() or []
    except Exception as e:
        out["top5"] = []
        print(f"[dashboard] top5 fetch failed: {e}")

    # ---- Komoditas: emas, perak, dinar ----
    commodities = {"gold": {}, "silver": {}, "dinar": {}}
    try:
        r = client.get("/api/silver-dinar/prices")
        if r.status_code == 200:
            sd = r.get_json() or {}
            commodities["silver"] = sd.get("silver", {})
            commodities["dinar"]  = sd.get("dinar", {})
            commodities["silver_spot"] = sd.get("silver_spot", {})
    except Exception:
        pass

    # Emas: pakai history → RSI
    gold_rsi = None
    gold_last_price = None
    try:
        r = client.get("/api/gold/history")
        if r.status_code == 200:
            hist = r.get_json() or []
            if hist:
                gold_last_price = float(hist[-1].get("price") or 0)
                gold_rsi = gold_rsi_from_history(hist, period=14)
    except Exception:
        pass

    # Prediksi emas 1d
    gold_prediction_1d = None
    try:
        r = client.get("/api/gold/prediction?horizon=1d")
        if r.status_code == 200:
            gold_prediction_1d = r.get_json()
    except Exception:
        pass

    def _signal_from_rsi(rsi):
        if rsi is None:
            return "N/A"
        if rsi >= 70:
            return "SELL (Overbought)"
        if rsi <= 30:
            return "BUY (Oversold)"
        if rsi >= 55:
            return "HOLD (Bullish)"
        if rsi <= 45:
            return "ACCUMULATE"
        return "HOLD"

    commodities["gold"] = {
        "price_idr_per_gram": gold_last_price,
        "rsi": gold_rsi,
        "signal": _signal_from_rsi(gold_rsi),
        "prediction_1d": gold_prediction_1d,
    }
    out["commodities"] = commodities

    # ---- Alert aktif hari ini ----
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        daily_file = os.path.join(BASE_DIR, "logs", "alerts", f"{today}.json")
        if os.path.exists(daily_file):
            with open(daily_file, "r", encoding="utf-8") as f:
                alerts = _json.load(f) or []
        else:
            alerts = []
        # Sort by severity
        sev_rank = {"high": 3, "medium": 2, "low": 1}
        alerts.sort(key=lambda a: sev_rank.get(a.get("severity"), 0), reverse=True)
        out["alerts"] = alerts[:10]  # top 10
        out["alerts_count"] = len(alerts)
    except Exception as e:
        out["alerts"] = []
        out["alerts_count"] = 0

    # ---- US portfolio value (untuk 4-bucket allocation) ----
    # Hitung nilai US portfolio dalam Rupiah. Caranya:
    #   - Baca portfolio_us.csv (harga beli + lot dalam USD)
    #   - Pakai current price dari cache history (last close)
    #   - Convert ke IDR pakai USDIDR=X
    us_portfolio_value_rp = 0.0
    try:
        if os.path.exists(US_PORTFOLIO_FILE):
            usdf = pd.read_csv(US_PORTFOLIO_FILE)
            if not usdf.empty:
                # Get USDIDR rate (TTL 6h kalau market closed via cache adaptif)
                usdidr_rate = 16000.0  # fallback default
                try:
                    fx_hist = cache.get_history("USDIDR=X", period="5d", ttl_minutes=60)
                    if fx_hist is not None and not fx_hist.empty:
                        usdidr_rate = float(fx_hist["Close"].iloc[-1])
                except Exception:
                    pass
                us_value_usd = 0.0
                for _, row in usdf.iterrows():
                    tk = str(row["Ticker"]).upper()
                    lot = float(row.get("Jumlah Lot", 0) or 0)
                    try:
                        h = cache.get_history(tk, period="5d", ttl_minutes=60, market="US")
                        if h is not None and not h.empty:
                            us_value_usd += float(h["Close"].iloc[-1]) * lot
                    except Exception:
                        # fallback ke harga beli kalau fetch gagal
                        us_value_usd += float(row.get("Harga Beli", 0) or 0) * lot
                us_portfolio_value_rp = us_value_usd * usdidr_rate
    except Exception as e:
        log.warning("compute US portfolio value failed: %s", e)
        us_portfolio_value_rp = 0.0

    # ---- Allocation engine (4-bucket: saham_idx, saham_us, emas, cash) ----
    # broker_cash_rp dari aggregator SUDAH include pegadaian_cash. Jangan tambah lagi.
    try:
        out["allocation"] = compute_allocation(
            market_status=out["ihsg"],
            alerts_today=out["alerts"],
            decisions=decisions,
            gold_signal={"rsi": gold_rsi},
            portfolio_value_rp=portfolio_value_rp,
            broker_cash_rp=broker_cash_rp,   # ← canonical (sudah include pegadaian cash)
            gold_value_rp=pegadaian_emas_value_rp,
            us_portfolio_value_rp=us_portfolio_value_rp,
            # us_market_status (SPX vs MA50) di-fetch lazy: skip dulu untuk performa,
            # rebalancer akan pakai baseline US 15% kalau tidak ada signal SPX.
        )
        out["us_portfolio_value_rp"] = round(us_portfolio_value_rp, 0)
    except Exception as e:
        out["allocation"] = {"error": str(e)}

    # ============================================================
    # SIZING DALAM RUPIAH KONKRET — pakai canonical total dari aggregator
    # supaya angka Dashboard IDENTIK dengan Tab Portofolio.
    # ============================================================
    total_asset_rp = float(canonical.get("total_asset_rp") or 0)
    out["portfolio"]["total_asset_rp"] = round(total_asset_rp, 0)

    # Build lookup harga sekarang per ticker dari portfolio + top5 (cepat & cukup)
    price_lookup = {}
    for p in portfolio_items:
        t = (p.get("ticker") or "").upper()
        pr = float(p.get("sekarang") or 0)
        if t and pr > 0:
            price_lookup[t] = pr
    for s in (out["top5"] or []):
        t = (s.get("ticker") or "").upper()
        pr = float(s.get("current_price") or 0)
        if t and pr > 0 and t not in price_lookup:
            price_lookup[t] = pr

    # Augment ALLOCATION dengan rupiah konkret (4-bucket: IDX / US / Emas / Cash)
    if out.get("allocation") and "target" in out["allocation"]:
        alloc = out["allocation"]
        target = alloc.get("target", {})
        current = alloc.get("current", {})
        # Include US portfolio dalam total asset supaya alokasi proporsional
        # (canonical total_asset_rp dari aggregator belum tahu tentang US holdings).
        total_with_us_rp = total_asset_rp + us_portfolio_value_rp
        # Daftar bucket modern (4): saham_idx, saham_us, emas, cash
        BUCKETS = ("saham_idx", "saham_us", "emas", "cash")
        alloc["amounts"] = {
            "total_asset_rp": round(total_with_us_rp, 0),
            "us_portfolio_value_rp": round(us_portfolio_value_rp, 0),
            "target_rp":  {k: round(target.get(k, 0) * total_with_us_rp, 0) for k in BUCKETS},
            "current_rp": {k: round(current.get(k, 0) * total_with_us_rp, 0) for k in BUCKETS},
        }
        # Backward-compat: tetap sediakan key "saham" (= saham_idx + saham_us)
        alloc["amounts"]["target_rp"]["saham"] = (
            alloc["amounts"]["target_rp"]["saham_idx"] + alloc["amounts"]["target_rp"]["saham_us"]
        )
        alloc["amounts"]["current_rp"]["saham"] = (
            alloc["amounts"]["current_rp"]["saham_idx"] + alloc["amounts"]["current_rp"]["saham_us"]
        )
        # Gap = target - current. Positive = perlu BUY/akumulasi, Negative = perlu kurangi.
        alloc["amounts"]["gap_rp"] = {
            k: round(alloc["amounts"]["target_rp"][k] - alloc["amounts"]["current_rp"][k], 0)
            for k in (*BUCKETS, "saham")
        }

    # ---- Per-action sizing (Taichi rule: 50% idle money / n_stocks_to_trade) ----
    # Trading budget = total_asset × target_saham_pct × 50% (hemat: pakai trading fund Taichi)
    target_saham_pct = (out.get("allocation") or {}).get("target", {}).get("saham", 0.60)
    saham_budget_rp = total_asset_rp * target_saham_pct
    trading_fund_rp = saham_budget_rp * 0.5  # Taichi: 50% idle untuk trading aktif

    # Sizing untuk action plan
    top_actions = (out.get("action_plan") or {}).get("top_actions") or []
    n_buy_actions = sum(1 for a in top_actions if a.get("action") == "BUY")
    n_buy_actions = max(n_buy_actions, 1)
    bid_fund_per_ticker = trading_fund_rp / n_buy_actions if n_buy_actions > 0 else 0

    enriched_actions = []
    for a in top_actions:
        ticker = (a.get("ticker") or "").upper()
        price = price_lookup.get(ticker, 0.0)
        sizing = {"price": price, "lot": 0, "amount_rp": 0, "note": ""}

        if a.get("action") == "SELL":
            # SELL dari portfolio — sell semua lot yang dimiliki
            held = next((p for p in portfolio_items
                         if (p.get("ticker") or "").upper() == ticker), None)
            if held:
                lot = int(float(held.get("lot") or 0))
                px = float(held.get("sekarang") or price or 0)
                amount = lot * 100 * px
                pnl_pct = float(held.get("pnl") or 0)
                sizing = {
                    "price": round(px, 2),
                    "lot": lot,
                    "amount_rp": round(amount, 0),
                    "note": f"Jual semua {lot} lot @ Rp{px:,.0f} → terima Rp{amount:,.0f} "
                            f"(P/L: {pnl_pct:+.2f}%)"
                }
        elif a.get("action") == "BUY":
            # BUY watchlist — sizing Taichi
            if price > 0 and bid_fund_per_ticker > 0:
                # Total lot ideal untuk ticker ini (split jadi 3 entry Ob1/Ob2/Ob3)
                total_lot = max(1, int(bid_fund_per_ticker / price / 100))
                ob1_lot = max(1, int(total_lot * 0.20))   # moderat profile
                ob2_lot = max(1, int(total_lot * 0.30))
                ob3_lot = max(0, total_lot - ob1_lot - ob2_lot)
                ob1_amount = ob1_lot * 100 * price
                total_amount = total_lot * 100 * price
                sizing = {
                    "price": round(price, 2),
                    "lot": total_lot,
                    "amount_rp": round(total_amount, 0),
                    "ob1_lot": ob1_lot,
                    "ob1_price": round(price, 2),
                    "ob1_amount_rp": round(ob1_amount, 0),
                    "ob2_lot": ob2_lot,
                    "ob2_price": round(price * 0.985, 2),
                    "ob3_lot": ob3_lot,
                    "ob3_price": round(price * 0.970, 2),
                    "note": f"Beli total {total_lot} lot Rp{total_amount:,.0f}. "
                            f"Entry 1: {ob1_lot} lot @ Rp{price:,.0f} = Rp{ob1_amount:,.0f}"
                }
            else:
                sizing["note"] = "Harga tidak tersedia / budget habis"
        enriched_actions.append({**a, "sizing": sizing})

    if out.get("action_plan"):
        out["action_plan"]["top_actions"] = enriched_actions
        out["action_plan"]["budget"] = {
            "total_asset_rp": round(total_asset_rp, 0),
            "saham_budget_rp": round(saham_budget_rp, 0),
            "trading_fund_rp": round(trading_fund_rp, 0),
            "bid_fund_per_ticker_rp": round(bid_fund_per_ticker, 0),
            "n_buy_slots": n_buy_actions,
        }

    # Sizing untuk Top 5 + Trading Score multi-factor (Layer 3)
    top5_with_sizing = []
    for s in (out.get("top5") or []):
        ticker = (s.get("ticker") or "").upper()
        price = float(s.get("current_price") or price_lookup.get(ticker) or 0)
        sizing = None
        if price > 0 and bid_fund_per_ticker > 0:
            total_lot = max(1, int(bid_fund_per_ticker / price / 100))
            total_amount = total_lot * 100 * price
            sizing = {
                "price": round(price, 2),
                "lot": total_lot,
                "amount_rp": round(total_amount, 0),
            }
        # Trading score multi-factor (Teknikal 40 + Global 30 + Sektor 20 + Syariah 10)
        try:
            trading_score = compute_trading_score(
                stock=s,
                global_factor=out.get("global_factor"),
                sector_benchmark=None,
            )
        except Exception as e:
            log.debug("trading_score for %s failed: %s", ticker, e)
            trading_score = None
        top5_with_sizing.append({**s, "sizing": sizing, "trading_score": trading_score})
    out["top5"] = top5_with_sizing

    # ---- Emas sizing: berapa gram emas yang perlu di-buy/sell untuk capai target? ----
    if out.get("allocation", {}).get("amounts") and gold_last_price:
        emas_gap_rp = out["allocation"]["amounts"]["gap_rp"].get("emas", 0)
        emas_gram = emas_gap_rp / gold_last_price if gold_last_price > 0 else 0
        if commodities.get("gold"):
            commodities["gold"]["sizing"] = {
                "gap_rp": emas_gap_rp,
                "gap_gram": round(emas_gram, 2),
                "note": (
                    f"Beli ~{emas_gram:.1f} gram emas (Rp{emas_gap_rp:,.0f}) "
                    f"untuk capai alokasi target"
                    if emas_gram > 0.1
                    else (f"Jual ~{abs(emas_gram):.1f} gram emas untuk capai target"
                          if emas_gram < -0.1
                          else "Alokasi emas sudah pas")
                )
            }

    # ============================================================
    # DAILY BUY PLAN — Priority-based budget allocator
    # ------------------------------------------------------------
    # Gabungkan semua BUY candidate (saham IDX + emas + dinar),
    # ranking by composite score (urgency × confidence × expected_return),
    # alokasi greedy dgn cap = total_asset_rp (saham + emas + cash).
    # Item yang tidak muat ditandai status="DEFERRED".
    # ============================================================
    candidates_buy = []
    seen_tickers = set()

    # 1) Saham IDX dari enriched_actions (top_actions) — sudah ada sizing Taichi
    for a in enriched_actions:
        if a.get("action") != "BUY":
            continue
        tk = (a.get("ticker") or "").upper()
        if not tk or tk in seen_tickers:
            continue
        seen_tickers.add(tk)
        candidates_buy.append(
            from_buy_decision(a, a.get("sizing", {}) or {}, asset_class="saham_idx")
        )

    # 2) Saham IDX dari all_buy yang belum masuk top_actions
    for a in (out.get("action_plan", {}).get("all_buy") or []):
        if a.get("action") != "BUY":
            continue
        tk = (a.get("ticker") or "").upper()
        if not tk or tk in seen_tickers:
            continue
        seen_tickers.add(tk)
        price = float(price_lookup.get(tk, 0.0) or 0.0)
        if price > 0 and bid_fund_per_ticker > 0:
            total_lot = max(1, int(bid_fund_per_ticker / price / 100))
            sizing = {
                "price": price,
                "lot": total_lot,
                "amount_rp": total_lot * 100 * price,
            }
        else:
            sizing = {"price": price, "lot": 0, "amount_rp": 0}
        candidates_buy.append(
            from_buy_decision(a, sizing, asset_class="saham_idx")
        )

    # 3) Emas: pakai gap_rp positif dari rebalancer + expected return dari prediction_1d
    emas_gap_rp_v = (out.get("allocation", {}).get("amounts", {}).get("gap_rp", {}) or {}).get("emas", 0)
    if emas_gap_rp_v and emas_gap_rp_v > 0 and gold_last_price:
        expected_return_emas = 0.0
        if isinstance(gold_prediction_1d, dict):
            agents_pred = gold_prediction_1d.get("agents") or []
            if agents_pred:
                expected_return_emas = sum(
                    float(ag.get("change_sell_pct") or 0) for ag in agents_pred
                ) / len(agents_pred)
        urg_emas, conf_emas = "MEDIUM", "MEDIUM"
        if gold_rsi is not None:
            if gold_rsi <= 30:
                urg_emas, conf_emas = "HIGH", "HIGH"
            elif gold_rsi >= 70:
                urg_emas, conf_emas = "LOW", "LOW"
        emas_gram_buy = float(emas_gap_rp_v) / float(gold_last_price)
        candidates_buy.append(from_commodity(
            name="Emas (Pegadaian)",
            asset_class="emas",
            price_per_unit=float(gold_last_price),
            requested_gram_or_count=round(emas_gram_buy, 2),
            expected_return_pct=expected_return_emas,
            urgency=urg_emas,
            confidence=conf_emas,
            reason=(
                f"Gap alokasi emas Rp{emas_gap_rp_v:,.0f} "
                f"(RSI {gold_rsi if gold_rsi is not None else 'N/A'})"
            ),
            meta={
                "rsi": gold_rsi,
                "signal": commodities.get("gold", {}).get("signal"),
                "gap_rp": emas_gap_rp_v,
            },
        ))

    # 4) Dinar: fetch prediction 1d, kalau cuan > threshold tambahkan candidate
    dinar_prediction_1d = None
    try:
        rd = client.get("/api/dinar/prediction?horizon=1d")
        if rd.status_code == 200:
            dinar_prediction_1d = rd.get_json()
    except Exception:
        dinar_prediction_1d = None

    dinar_prices_list = (commodities.get("dinar") or {}).get("dinar_prices") or []
    if dinar_prediction_1d and dinar_prediction_1d.get("success") and dinar_prices_list:
        expected_return_dinar = float(dinar_prediction_1d.get("change_sell_pct") or 0.0)
        one_dinar = next((d for d in dinar_prices_list if d.get("name") == "1 Dinar"), None)
        if one_dinar:
            price_1d = float(one_dinar.get("sell") or 0.0)
            if price_1d > 0 and expected_return_dinar > 0.5:
                candidates_buy.append(from_commodity(
                    name="1 Dinar (DinarKR)",
                    asset_class="dinar",
                    price_per_unit=price_1d,
                    requested_gram_or_count=1.0,
                    expected_return_pct=expected_return_dinar,
                    urgency="MEDIUM" if expected_return_dinar > 1.0 else "LOW",
                    confidence="MEDIUM" if expected_return_dinar > 1.0 else "LOW",
                    reason=f"Prediksi cuan 1d +{expected_return_dinar:.2f}%",
                    meta={"horizon": "1d", "predicted_sell": dinar_prediction_1d.get("predicted_sell")},
                ))

    # 5) Perak: belum ada endpoint prediction → skip (bisa ditambah nanti)

    # 6) Run allocator dengan cap = total aset (saham + emas + cash)
    budget_cap = float(canonical.get("total_asset_rp") or 0)
    alloc_plan = allocate_budget(
        candidates=candidates_buy,
        budget_cap_rp=budget_cap,
        allow_partial=False,   # all-or-nothing → item kalah prioritas → DEFERRED
    )

    out["daily_buy_plan"] = {
        "budget_cap_rp":  alloc_plan["budget_cap_rp"],
        "used_rp":        alloc_plan["used_rp"],
        "remaining_rp":   alloc_plan["remaining_rp"],
        "utilization_pct": alloc_plan["utilization_pct"],
        "n_candidates":   alloc_plan["n_candidates"],
        "n_allocated":    alloc_plan["n_allocated"],
        "n_deferred":     alloc_plan["n_deferred"],
        "by_class_rp":    alloc_plan["by_class_rp"],
        "items":          candidates_to_dict(alloc_plan["candidates"]),
        "note": (
            "Item diranking by composite score (urgency × confidence × expected_return %). "
            "Total alokasi dijamin ≤ total aset (saham + emas + cash). "
            "Item yang tidak muat ditandai status='DEFERRED'."
        ),
    }

    # ============================================================
    # ROTATION ADVISOR (Layer 2: Reserve Asset Pool emas ↔ saham)
    # Recommend-only: tampilkan suggestion, user eksekusi manual.
    # ============================================================
    try:
        out["rotation_advisor"] = generate_rotation_suggestions(
            global_factor=out.get("global_factor") or {},
            allocation=out.get("allocation") or {},
            top_stocks_with_score=out.get("top5") or [],
            market_status=out.get("ihsg") or {},
            ts_entry_threshold=TS_ENTRY,
            ts_watchlist_threshold=TS_WATCHLIST,
        )
    except Exception as e:
        log.warning("rotation_advisor failed: %s", e)
        out["rotation_advisor"] = {
            "trigger_status": "HOLD_ALL",
            "global_status": (out.get("global_factor") or {}).get("status", "NEUTRAL"),
            "narrative": f"Rotation advisor fallback (error: {e})",
            "suggestions": [],
        }

    # ---- Data freshness (umur cache harga) untuk badge di UI ----
    try:
        out["data_freshness"] = _data_freshness()
    except Exception as e:
        out["data_freshness"] = {"label": "Tidak diketahui", "error": str(e)}

    return jsonify(out)


# ----------------------------- ROUTES: US STOCK MARKET ----------------------------- #
# Endpoint paralel ke IDX tapi untuk pasar saham AS (NYSE/NASDAQ).
# Universe: daftar_saham_syariah_us.csv (~50 ticker)
# Screening: AAOIFI (modules/aaoifi.py) — bukan DSN-MUI
# Master data: master_data_syariah_us.csv (di-build via `python build_master_us.py`)

US_UNIVERSE_FILE = os.path.join(BASE_DIR, "daftar_saham_syariah_us.csv")
US_MASTER_FILE = os.path.join(BASE_DIR, "master_data_syariah_us.csv")
US_PORTFOLIO_FILE = os.path.join(BASE_DIR, "portfolio_us.csv")
_US_PORTFOLIO_LOCK = threading.Lock()

# Defensive imports
try:
    from modules.aaoifi import evaluate_from_yfinance_info
except Exception:
    evaluate_from_yfinance_info = None

try:
    from modules.market_hours import us_market_status, is_us_market_open
except Exception:
    def us_market_status():  # type: ignore
        return {"badge": "?", "is_market_open": False, "session": "UNKNOWN"}

    def is_us_market_open():  # type: ignore
        return False


def _load_us_master() -> pd.DataFrame:
    if not os.path.exists(US_MASTER_FILE):
        return pd.DataFrame()
    try:
        return pd.read_csv(US_MASTER_FILE, keep_default_na=False)
    except Exception as e:
        log.warning("read US master failed: %s", e)
        return pd.DataFrame()


def _load_us_universe() -> pd.DataFrame:
    if not os.path.exists(US_UNIVERSE_FILE):
        return pd.DataFrame()
    try:
        return pd.read_csv(US_UNIVERSE_FILE)
    except Exception:
        return pd.DataFrame()


def _us_cache_seconds() -> int:
    """Browser cache TTL: panjang saat pasar US tutup, pendek saat buka."""
    try:
        return 60 if is_us_market_open() else 600  # 1 menit vs 10 menit
    except Exception:
        return 300  # default 5 menit


def _add_us_cache_headers(response, ttl_seconds=None):
    """Set Cache-Control supaya browser cache hasil endpoint US."""
    ttl = ttl_seconds if ttl_seconds is not None else _us_cache_seconds()
    response.headers["Cache-Control"] = f"public, max-age={ttl}"
    return response


@app.route("/api/us/market_status", methods=["GET"])
def api_us_market_status():
    """Status NYSE/NASDAQ session untuk badge UI (BUKA/PRE/AFTER/TUTUP)."""
    return jsonify(us_market_status())


@app.route("/api/us/universe", methods=["GET"])
def api_us_universe():
    """Daftar saham US Sharia universe (dari daftar_saham_syariah_us.csv)."""
    df = _load_us_universe()
    if df.empty:
        return jsonify({"tickers": [], "count": 0,
                        "note": "Universe file belum ada di " + US_UNIVERSE_FILE})
    return jsonify({
        "tickers": df.to_dict(orient="records"),
        "count": len(df)
    })


@app.route("/api/us/master", methods=["GET"])
def api_us_master():
    """Master fundamental data US Sharia (dari master_data_syariah_us.csv)."""
    df = _load_us_master()
    if df.empty:
        resp = jsonify({
            "data": [], "count": 0,
            "note": "Master US belum di-build. Jalankan: python build_master_us.py"
        })
        return _add_us_cache_headers(resp, ttl_seconds=60)  # quick retry kalau belum di-build
    resp = jsonify({"data": df.to_dict(orient="records"), "count": len(df)})
    return _add_us_cache_headers(resp)


@app.route("/api/us/index/<index_symbol>", methods=["GET"])
def api_us_index_history(index_symbol):
    """
    Ambil history indeks US untuk chart. Symbol diterima:
      - GSPC   → S&P 500 (^GSPC)
      - IXIC   → NASDAQ Composite (^IXIC)
      - NDX    → NASDAQ 100 (^NDX)
      - DJI    → Dow Jones (^DJI)
    """
    sym_map = {"GSPC": "^GSPC", "IXIC": "^IXIC", "NDX": "^NDX", "DJI": "^DJI"}
    yf_sym = sym_map.get(index_symbol.upper(), f"^{index_symbol.upper()}")
    period = request.args.get("period", "1y")
    try:
        df = cache.get_history(yf_sym, period=period, ttl_minutes=60)
        if df is None or df.empty:
            return jsonify({"ok": False, "error": "no data", "symbol": yf_sym}), 503
        out = [
            {"date": str(idx)[:10], "close": float(row["Close"]),
             "volume": int(row.get("Volume") or 0)}
            for idx, row in df.iterrows()
        ]
        resp = jsonify({"ok": True, "symbol": yf_sym, "period": period,
                        "count": len(out), "data": out})
        return _add_us_cache_headers(resp)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "symbol": yf_sym}), 500


@app.route("/api/us/top5", methods=["GET"])
def api_us_top5():
    """
    Top 5 saham US Sharia hari ini berdasarkan ranking sederhana:
      - Compliant AAOIFI (PASS atau NEEDS_AUDIT)
      - PER < 30 (filter overvalued ekstrem)
      - Sort by ROE descending
    """
    df = _load_us_master()
    if df.empty:
        return jsonify({
            "data": [],
            "note": "Master US belum di-build. Jalankan: python build_master_us.py"
        })

    # Filter: bukan FAIL
    df = df[df["AAOIFI Status"].isin(["PASS", "NEEDS_AUDIT"])]

    # Parse ROE & PER ke float untuk sorting
    def _parse_pct(v):
        try:
            return float(str(v).replace("%", "").replace("N/A", "nan"))
        except Exception:
            return float("nan")

    def _parse_x(v):
        try:
            return float(str(v).replace("x", "").replace("N/A", "nan"))
        except Exception:
            return float("nan")

    df = df.copy()
    df["_roe"] = df["ROE"].map(_parse_pct)
    df["_per"] = df["PER"].map(_parse_x)
    df = df[df["_per"].between(0, 30, inclusive="both") | df["_per"].isna()]
    df = df.sort_values("_roe", ascending=False, na_position="last").head(5)

    out = []
    for _, row in df.iterrows():
        out.append({
            "ticker": row["Ticker"],
            "name": row.get("Nama Perusahaan", ""),
            "sector": row.get("Sektor", ""),
            "market_cap": row.get("MarketCap", ""),
            "price": row.get("MP", ""),
            "per": row.get("PER", ""),
            "pbv": row.get("PBV", ""),
            "roe": row.get("ROE", ""),
            "dividend_yield": row.get("Dividend Yield", ""),
            "aaoifi_status": row.get("AAOIFI Status", ""),
            "aaoifi_reason": row.get("AAOIFI Reason", ""),
        })
    resp = jsonify({"data": out, "count": len(out)})
    return _add_us_cache_headers(resp)


@app.route("/api/us/action_plan", methods=["GET"])
def api_us_action_plan():
    """
    Action plan US Stock hari ini — struktur identik dengan IDX action_plan.
    SELL candidates: scan portfolio_us.csv → pnl_pct <= cut_loss (URGENT) atau >= take_profit (HIGH).
    BUY candidates: top 3 dari /api/us/top5 (PASS=HIGH confidence, NEEDS_AUDIT=MEDIUM).
    Sizing: lot integer, harga USD, amount_usd = lot*price, amount_rp = amount_usd*USDIDR.
    Budget Taichi rule: trading_fund = target_saham_us_rp * 50%.
    """
    out = {
        "verdict": None,
        "n_buy": 0, "n_sell": 0, "n_hold": 0,
        "top_actions": [],
        "all_sell": [], "all_buy": [],
        "budget": None,
        "usdidr_rate": None,
    }

    # ---- USDIDR rate (cache 60 min) ----
    usdidr = 16000.0
    try:
        fx = cache.get_history("USDIDR=X", period="5d", ttl_minutes=60)
        if fx is not None and not fx.empty:
            usdidr = float(fx["Close"].iloc[-1])
    except Exception:
        pass
    out["usdidr_rate"] = round(usdidr, 2)

    # ---- Trading thresholds ikut TRADING_MODE (sama dengan IDX) ----
    try:
        cl_pct = get_cut_loss_pct()       # negative number, mis -3.0
        tp_pct = get_take_profit_pct()    # positive, mis 6.0
    except Exception:
        cl_pct, tp_pct = -3.0, 6.0

    # ---- SELL candidates dari portfolio US ----
    sell_list = []
    if os.path.exists(US_PORTFOLIO_FILE):
        try:
            usdf = pd.read_csv(US_PORTFOLIO_FILE)
            # Prefetch concurrent harga 5d untuk semua holding US sekaligus,
            # agar loop di bawah hit cache (bukan fetch yfinance sekuensial).
            try:
                _prefetch_histories(
                    usdf["Ticker"].tolist(), period="5d",
                    ttl_minutes=60, market="US",
                )
            except Exception:
                pass
            for _, row in usdf.iterrows():
                tk = str(row["Ticker"]).upper()
                harga_beli = float(row.get("Harga Beli", 0) or 0)
                lot = int(row.get("Jumlah Lot", 0) or 0)
                if lot <= 0 or harga_beli <= 0:
                    continue
                try:
                    h = cache.get_history(tk, period="5d", ttl_minutes=60, market="US")
                    current = float(h["Close"].iloc[-1]) if h is not None and not h.empty else 0.0
                except Exception:
                    current = 0.0
                if current <= 0:
                    continue
                pnl_pct = (current - harga_beli) / harga_beli * 100
                if pnl_pct <= cl_pct:
                    sell_list.append({
                        "ticker": tk, "action": "SELL", "urgency": "URGENT",
                        "confidence": "HIGH",
                        "reason": f"Cut loss — PnL {pnl_pct:+.2f}% ≤ {cl_pct:.1f}%",
                        "sizing": {
                            "lot": lot, "price": round(current, 2),
                            "amount_usd": round(lot * current, 2),
                            "amount_rp": round(lot * current * usdidr, 0),
                            "currency": "USD",
                            "note": "Eksekusi cut-loss disiplin — jangan tunggu rebound",
                        },
                    })
                elif pnl_pct >= tp_pct:
                    sell_list.append({
                        "ticker": tk, "action": "SELL", "urgency": "HIGH",
                        "confidence": "HIGH",
                        "reason": f"Take profit — PnL {pnl_pct:+.2f}% ≥ +{tp_pct:.1f}%",
                        "sizing": {
                            "lot": lot, "price": round(current, 2),
                            "amount_usd": round(lot * current, 2),
                            "amount_rp": round(lot * current * usdidr, 0),
                            "currency": "USD",
                            "note": "Profit-take — kunci profit, hindari serakah",
                        },
                    })
        except Exception as e:
            log.warning("US sell scan failed: %s", e)

    # ---- BUY candidates dari master US (mirror /api/us/top5 logic) ----
    buy_list = []
    df_master = _load_us_master()
    if not df_master.empty:
        df = df_master[df_master["AAOIFI Status"].isin(["PASS", "NEEDS_AUDIT"])].copy()
        def _parse_pct(v):
            try: return float(str(v).replace("%", "").replace("N/A", "nan"))
            except Exception: return float("nan")
        def _parse_x(v):
            try: return float(str(v).replace("x", "").replace("N/A", "nan"))
            except Exception: return float("nan")
        df["_roe"] = df["ROE"].map(_parse_pct)
        df["_per"] = df["PER"].map(_parse_x)
        df = df[df["_per"].between(0, 30, inclusive="both") | df["_per"].isna()]
        df = df.sort_values("_roe", ascending=False, na_position="last").head(5)

        # Budget: dari dashboard allocation kalau ada — ambil us_target_rp;
        # kalau tidak, fallback baseline 15% × default 10M.
        try:
            dr = client.get("/api/dashboard") if False else None  # avoid circular
        except Exception:
            dr = None
        # Pakai pendekatan langsung: hitung dari portfolio_us + IDX portfolio canonical
        try:
            us_canonical = get_canonical_assets()
            total_asset_rp = float(us_canonical.get("total_asset_rp") or 0)
        except Exception:
            total_asset_rp = 0.0
        # Tambah US value
        us_value_rp = sum(s["sizing"]["amount_rp"] for s in sell_list)  # rough proxy
        if os.path.exists(US_PORTFOLIO_FILE):
            try:
                usdf2 = pd.read_csv(US_PORTFOLIO_FILE)
                for _, r in usdf2.iterrows():
                    tk = str(r["Ticker"]).upper()
                    lot = float(r.get("Jumlah Lot", 0) or 0)
                    try:
                        h = cache.get_history(tk, period="5d", ttl_minutes=60, market="US")
                        cur = float(h["Close"].iloc[-1]) if h is not None and not h.empty else float(r.get("Harga Beli", 0) or 0)
                    except Exception:
                        cur = float(r.get("Harga Beli", 0) or 0)
                    us_value_rp += lot * cur * usdidr
            except Exception:
                pass
        total_with_us = total_asset_rp + us_value_rp
        # Target US bucket: baseline 15% (atau ambil dari rebalancer BASELINE)
        try:
            from modules.rebalancer import BASELINE
            us_target_pct = BASELINE.get("saham_us", 0.15)
        except Exception:
            us_target_pct = 0.15
        us_target_rp = total_with_us * us_target_pct
        # Taichi rule: 50% idle untuk trading aktif
        us_trading_fund_rp = us_target_rp * 0.5
        n_buy_slots = min(3, len(df))
        bid_fund_per_ticker_rp = us_trading_fund_rp / n_buy_slots if n_buy_slots else 0
        bid_fund_per_ticker_usd = bid_fund_per_ticker_rp / usdidr if usdidr > 0 else 0

        out["budget"] = {
            "total_asset_rp": round(total_with_us, 0),
            "us_target_rp":   round(us_target_rp, 0),
            "trading_fund_rp": round(us_trading_fund_rp, 0),
            "n_buy_slots":     n_buy_slots,
            "bid_fund_per_ticker_rp":  round(bid_fund_per_ticker_rp, 0),
            "bid_fund_per_ticker_usd": round(bid_fund_per_ticker_usd, 2),
            "usdidr_rate": round(usdidr, 2),
        }

        for _, row in df.head(n_buy_slots).iterrows():
            tk = row["Ticker"]
            status = row.get("AAOIFI Status", "")
            try:
                price = float(str(row.get("MP", "")).replace("$", ""))
            except Exception:
                price = 0.0
            lot = int(bid_fund_per_ticker_usd / price) if price > 0 else 0
            amount_usd = round(lot * price, 2)
            amount_rp = round(amount_usd * usdidr, 0)
            confidence = "HIGH" if status == "PASS" else "MEDIUM"
            note_aaoifi = ("✅ AAOIFI lolos rasio (audit non-permissible income disarankan)"
                           if status == "PASS"
                           else "⚠️ Lolos rasio numerik, AUDIT non-permissible income manual via Zoya")
            buy_list.append({
                "ticker": tk, "action": "BUY",
                "urgency": "HIGH" if status == "PASS" else "MEDIUM",
                "confidence": confidence,
                "reason": (f"{row.get('Sektor','')} | ROE {row.get('ROE','–')} | "
                           f"PER {row.get('PER','–')} | Div Yld {row.get('Dividend Yield','–')} | "
                           f"AAOIFI {status}"),
                "sizing": {
                    "lot": lot, "price": round(price, 2),
                    "amount_usd": amount_usd,
                    "amount_rp": amount_rp,
                    "currency": "USD",
                    "note": note_aaoifi,
                },
            })

    # ---- Aggregate verdict ----
    n_sell = len(sell_list)
    n_buy = len(buy_list)
    out["n_sell"] = n_sell
    out["n_buy"] = n_buy
    out["all_sell"] = sell_list[:5]
    out["all_buy"] = buy_list[:5]
    # Top actions: urgent sell dulu, lalu top buy
    out["top_actions"] = sell_list[:3] + buy_list[:3]

    if n_sell == 0 and n_buy == 0:
        out["verdict"] = "⚖️ Tidak ada aksi prioritas US hari ini — HOLD posisi yang ada."
    elif n_sell >= 1:
        out["verdict"] = f"🔴 {n_sell} aksi exit US prioritas — eksekusi cut-loss / take-profit dulu."
    else:
        out["verdict"] = f"🟢 {n_buy} kandidat BUY US Sharia tersedia (AAOIFI screened)."

    resp = jsonify(out)
    return _add_us_cache_headers(resp, ttl_seconds=120)


@app.route("/api/us/portfolio", methods=["GET"])
def api_us_portfolio_get():
    """List US portfolio dari portfolio_us.csv (format sama dengan portfolio.csv)."""
    if not os.path.exists(US_PORTFOLIO_FILE):
        return jsonify([])
    df = pd.read_csv(US_PORTFOLIO_FILE)
    if df.empty:
        return jsonify([])

    out = []
    for _, row in df.iterrows():
        ticker = str(row["Ticker"]).upper()
        harga_beli = float(row.get("Harga Beli", 0) or 0)
        lot = int(row.get("Jumlah Lot", 0) or 0)
        # Fetch current price (US: harga dalam USD)
        try:
            hist = cache.get_history(ticker, period="5d", ttl_minutes=60, market="US")
            current = float(hist["Close"].iloc[-1]) if hist is not None and not hist.empty else 0.0
        except Exception:
            current = 0.0
        pnl = ((current - harga_beli) / harga_beli * 100) if harga_beli > 0 else 0.0
        out.append({
            "ticker": ticker,
            "harga_beli": harga_beli,
            "lot": lot,
            "sekarang": round(current, 2),
            "pnl": round(pnl, 2),
            "currency": "USD",
        })
    return jsonify(out)


@app.route("/api/us/portfolio", methods=["POST"])
def api_us_portfolio_add():
    """Tambah/update saham di portfolio US."""
    data = request.json or {}
    ticker = str(data.get("ticker", "")).upper().strip()
    try:
        harga = float(data.get("harga", 0))
        lot = int(data.get("lot", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid number"}), 400
    if not ticker or harga <= 0 or lot <= 0:
        return jsonify({"success": False, "error": "Invalid data"}), 400

    with _US_PORTFOLIO_LOCK:
        df = pd.DataFrame()
        if os.path.exists(US_PORTFOLIO_FILE):
            df = pd.read_csv(US_PORTFOLIO_FILE)
        if not df.empty and ticker in df["Ticker"].values:
            df.loc[df["Ticker"] == ticker, "Harga Beli"] = harga
            df.loc[df["Ticker"] == ticker, "Jumlah Lot"] = lot
        else:
            new_row = pd.DataFrame([{"Ticker": ticker, "Harga Beli": harga, "Jumlah Lot": lot}])
            df = pd.concat([df, new_row], ignore_index=True) if not df.empty else new_row
        _atomic_write_csv(df, US_PORTFOLIO_FILE)
    _invalidate_response_memo()
    return jsonify({"success": True})


@app.route("/api/us/portfolio/<ticker>", methods=["DELETE"])
def api_us_portfolio_delete(ticker):
    if not os.path.exists(US_PORTFOLIO_FILE):
        return jsonify({"success": False}), 404
    with _US_PORTFOLIO_LOCK:
        df = pd.read_csv(US_PORTFOLIO_FILE)
        df = df[df["Ticker"] != ticker.upper()]
        _atomic_write_csv(df, US_PORTFOLIO_FILE)
    _invalidate_response_memo()
    return jsonify({"success": True})


@app.route("/api/us/signal/<ticker>", methods=["GET"])
def api_us_signal(ticker):
    """Sinyal teknikal untuk 1 ticker US (RSI/MACD/MA/Bollinger via modules.technical_analysis)."""
    ticker = ticker.upper().strip()
    try:
        hist = cache.get_history(ticker, period="6mo", ttl_minutes=60, market="US")
        if hist is None or hist.empty:
            return jsonify({"ok": False, "error": "no history data"}), 503
        signals = compute_signals(hist)
        chart = chart_payload(hist)
        return jsonify({"ok": True, "ticker": ticker, "signals": signals, "chart": chart})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/us/build_master", methods=["POST"])
def api_us_build_master():
    """Trigger rebuild master_data_syariah_us.csv (background)."""
    try:
        subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, "build_master_us.py")],
            cwd=BASE_DIR,
        )
        return jsonify({"success": True,
                        "message": "Build US master dimulai (~2 menit untuk 50 ticker)."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ----------------------------- ROUTES: HEALTH & MARKET STATUS ----------------------------- #
# Endpoint baru (post-patch PERBAIKAN_SAHAM.md):
#   GET /api/health         → liveness/readiness, scheduler status, market session
#   GET /api/market_status  → status sesi IDX untuk UI badge (BUKA/JEDA/TUTUP)

@app.route("/api/health", methods=["GET"])
def api_health():
    """Liveness + readiness probe untuk uptime monitoring."""
    status = {
        "ok": True,
        "version": APP_VERSION,
        "now": pd.Timestamp.utcnow().isoformat(),
        "scheduler_started": bool(_SCHEDULER_STATE.get("started")),
        "scheduler_error": _SCHEDULER_STATE.get("error"),
        "files": {
            "portfolio_csv": os.path.exists(PORTFOLIO_FILE),
            "master_csv": os.path.exists(MASTER_FILE),
            "jii_csv": os.path.exists(JII_FILE),
            "broker_tx_csv": os.path.exists(BROKER_TX_FILE),
            "pegadaian_csv": os.path.exists(PEGADAIAN_FILE),
        },
        "market": market_status(),
        "trading_mode": os.environ.get("TRADING_MODE", "swing"),
    }
    # Kalau scheduler error → response 503 supaya monitoring/uptime page bisa
    # langsung sounding alarm.
    if _SCHEDULER_STATE.get("error"):
        status["ok"] = False
        return jsonify(status), 503
    return jsonify(status)


@app.route("/api/market_status", methods=["GET"])
def api_market_status():
    """Status sesi IDX (BUKA/JEDA/TUTUP/LIBUR/WEEKEND) untuk UI badge."""
    return jsonify(market_status())


# ----------------------------- SCHEDULER AUTO-START ----------------------------- #
# Bug pre-patch: start_scheduler() hanya dipanggil di blok `if __name__ == "__main__"`,
# jadi tidak pernah jalan saat di-launch via `gunicorn app:app`. Sekarang scheduler
# di-start saat module di-load (idempotent, dilindungi _SCHEDULER_LOCK).

_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STATE = {"started": False, "error": None, "scheduler": None}


def _maybe_start_scheduler():
    """Start scheduler sekali saja per process (worker gunicorn / dev flask).

    Dipanggil saat module load supaya jalan otomatis di gunicorn — bukan hanya
    di `python app.py`. Idempotent: panggilan kedua diabaikan.

    Env var SCHEDULER_DISABLED=1 → bypass (berguna saat run pipeline manual).
    """
    if os.environ.get("SCHEDULER_DISABLED", "").strip() in {"1", "true", "TRUE"}:
        log.info("Scheduler disabled via SCHEDULER_DISABLED env")
        return
    if start_scheduler is None:
        log.warning("modules.scheduler tidak tersedia — scheduler tidak start")
        return
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STATE["started"]:
            return
        try:
            sched = start_scheduler()
            _SCHEDULER_STATE["started"] = True
            _SCHEDULER_STATE["scheduler"] = sched
            log.info("Scheduler started OK (auto-start at module load)")
        except Exception as e:
            _SCHEDULER_STATE["error"] = str(e)
            log.exception("Scheduler auto-start FAILED: %s", e)


# Auto-start saat module di-load. gunicorn_config.py memakai preload_app=False
# (post-patch), jadi ini akan jalan sekali per worker, dilindungi lock.
_maybe_start_scheduler()


# ----------------------------- BOOT ----------------------------- #

if __name__ == "__main__":
    # Scheduler sudah di-auto-start di atas via _maybe_start_scheduler().
    # Blok ini cuma untuk `python app.py` (dev mode).
    port = int(os.environ.get("FLASK_RUN_PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, port=port, host="127.0.0.1")
