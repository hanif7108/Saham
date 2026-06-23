"""
TradingView Intraday Collector
==============================
Mengumpulkan harga intraday dari TradingView Desktop (via CDP) untuk dipakai
web app saat JAM BURSA IDX. Dijalankan terjadwal oleh scheduler — BUKAN per-request
(satu chart TradingView hanya bisa 1 simbol/waktu → polling serial & lambat).

Alur:
  scheduler → poll_and_store() → [gate jam bursa] → ensure_tradingview_up()
            → jalankan tools/tv_poll.mjs (Node, 1 koneksi CDP, loop simbol)
            → tulis cache/intraday_tv.json (atomik)

Web app membaca via get_intraday(ticker). Bila TradingView mati / di luar jam bursa,
collector skip dan web app otomatis fallback ke yfinance (data EOD/delayed).

Ini lapisan ENRICHMENT di atas yfinance, bukan pengganti.
"""

import fcntl
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request

logger = logging.getLogger("sharia.tv_collector")

# ----------------------------- Konfigurasi ----------------------------- #
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLLER = os.path.join(BASE_DIR, "tools", "tv_poll.mjs")
CACHE_PATH = os.path.join(BASE_DIR, "cache", "intraday_tv.json")
LOCK_PATH = os.path.join(BASE_DIR, "cache", "tv_poll.lock")
WATCHLIST_PATH = os.path.join(BASE_DIR, "watchlist.txt")
PORTFOLIO_PATH = os.path.join(BASE_DIR, "portfolio.csv")

CDP_PORT = int(os.environ.get("TV_CDP_PORT", "9222"))
CDP_URL = f"http://127.0.0.1:{CDP_PORT}/json/version"
EXCHANGE_PREFIX = os.environ.get("TV_EXCHANGE", "IDX")  # IDX:TICKER
MAX_SYMBOLS = int(os.environ.get("TV_MAX_SYMBOLS", "15"))
# Batas saham yang di-poll ON-DEMAND saat Funnel live (jaga agar scan tak terlalu lama).
MAX_ONDEMAND = int(os.environ.get("FUNNEL_TV_ONDEMAND_MAX", "12"))
POLL_TIMEOUT_S = int(os.environ.get("TV_POLL_TIMEOUT_S", "300"))
AUTO_RELAUNCH = os.environ.get("TV_AUTO_RELAUNCH", "1").strip() not in {"0", "false", "no"}
TV_APP = os.environ.get("TV_APP_NAME", "TradingView")


def _node_bin() -> str:
    return os.environ.get("TV_NODE_BIN") or shutil.which("node") or "/opt/homebrew/bin/node"


# ----------------------------- Simbol ----------------------------- #
def _read_lines(path: str) -> list:
    out = []
    try:
        with open(path) as f:
            for ln in f:
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    out.append(ln.split(",")[0].strip().upper())
    except FileNotFoundError:
        pass
    return out


def get_symbols() -> list:
    """Gabungan ticker portfolio + watchlist (unik, dibatasi MAX_SYMBOLS)."""
    tickers = []
    # portfolio.csv kolom 'Ticker'
    try:
        import csv
        with open(PORTFOLIO_PATH) as f:
            for row in csv.DictReader(f):
                t = (row.get("Ticker") or "").strip().upper()
                if t:
                    tickers.append(t)
    except FileNotFoundError:
        pass
    for t in _read_lines(WATCHLIST_PATH):
        tickers.append(t)
    # unik, jaga urutan
    seen, uniq = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:MAX_SYMBOLS]


# ----------------------------- Health-check ----------------------------- #
def cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(CDP_URL, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_tradingview_up() -> bool:
    """Pastikan TradingView + port CDP hidup. Relaunch sekali bila mati & diizinkan."""
    if cdp_alive():
        return True
    if not AUTO_RELAUNCH:
        logger.warning("CDP mati & auto-relaunch nonaktif")
        return False
    logger.warning("CDP port %s mati — relaunch TradingView", CDP_PORT)
    try:
        # Kill dulu: tangani kasus TradingView sudah jalan TANPA flag debug
        # (single-instance lock bikin 'open' tak berefek bila tak di-kill dulu).
        subprocess.run(["pkill", "-9", "-i", "-f", "TradingView"], check=False, timeout=10)
        time.sleep(3)
        subprocess.run(
            ["open", "-a", TV_APP, "--args", f"--remote-debugging-port={CDP_PORT}"],
            check=False, timeout=15,
        )
    except Exception as e:
        logger.error("gagal relaunch TradingView: %s", e)
        return False
    # tunggu boot + buka port (maks ~25s)
    for _ in range(13):
        time.sleep(2)
        if cdp_alive():
            logger.info("TradingView CDP kembali hidup")
            return True
    logger.error("TradingView CDP tetap mati setelah relaunch")
    return False


# ----------------------------- Poll & store ----------------------------- #
def _run_poller(symbols: list) -> list:
    arg = ",".join(f"{EXCHANGE_PREFIX}:{t}" for t in symbols)
    try:
        proc = subprocess.run(
            [_node_bin(), POLLER, arg],
            capture_output=True, text=True, timeout=POLL_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        logger.error("poller timeout setelah %ss", POLL_TIMEOUT_S)
        return []
    if proc.returncode == 2:
        logger.warning("poller: gagal konek CDP (%s)", (proc.stderr or "").strip()[:120])
        return []
    if proc.returncode != 0:
        logger.error("poller exit %s: %s", proc.returncode, (proc.stderr or "").strip()[:200])
        return []
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as e:
        logger.error("poller output bukan JSON valid: %s", e)
        return []


def _atomic_write(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def poll_and_store(force: bool = False) -> dict:
    """Satu siklus: gate jam bursa → ensure TV → poll → tulis cache. Return ringkasan.

    Dilindungi file-lock lintas-proses: bila >1 scheduler (gunicorn worker +
    run_scheduler.py) memicu bersamaan, hanya SATU yang jalan — sisanya skip.
    Mencegah dua poll berebut satu chart TradingView.
    """
    from modules.market_hours import is_connectivity_window

    if not force and not is_connectivity_window():
        logger.info("di luar jendela koneksi (±60mnt jam bursa) — skip poll TradingView")
        return {"status": "skipped_outside_window", "count": 0}

    symbols = get_symbols()
    if not symbols:
        return {"status": "no_symbols", "count": 0}

    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            logger.info("poll TradingView lain sedang jalan — skip")
            return {"status": "locked", "count": 0}

        if not ensure_tradingview_up():
            return {"status": "tv_down", "count": 0}

        return _poll_locked(symbols)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _poll_locked(symbols: list) -> dict:
    t0 = time.time()
    records = _run_poller(symbols)
    if not records:
        return {"status": "poll_failed", "count": 0}

    # bentuk store: { TICKER: {last, close, open, high, low, volume, ts, source} }
    store = _read_store()
    quotes = store.setdefault("quotes", {})
    ok = 0
    for r in records:
        if not r.get("ok"):
            continue
        q = r.get("quote") or {}
        sym = str(q.get("symbol", "")).split(":")[-1].upper()
        if not sym:
            continue
        quotes[sym] = {
            "last": q.get("last"),
            "close": q.get("close"),
            "open": q.get("open"),
            "high": q.get("high"),
            "low": q.get("low"),
            "volume": q.get("volume"),
            "ts": r.get("ts") or int(time.time()),
            "source": "tradingview_delayed",
        }
        ok += 1
    store["updated_at"] = int(time.time())
    store["elapsed_s"] = round(time.time() - t0, 1)
    _atomic_write(CACHE_PATH, store)
    logger.info("TV poll: %s/%s simbol ok dalam %.1fs", ok, len(symbols), store["elapsed_s"])
    return {"status": "ok", "count": ok, "total": len(symbols), "elapsed_s": store["elapsed_s"]}


# ----------------------------- Baca (untuk web app) ----------------------------- #
def _read_store() -> dict:
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"quotes": {}, "updated_at": 0}


def get_intraday(ticker: str, max_age_s: int = 1200):
    """Quote intraday TradingView terbaru utk 1 ticker, atau None bila tak ada/terlalu basi."""
    t = (ticker or "").strip().upper()
    q = _read_store().get("quotes", {}).get(t)
    if not q:
        return None
    if max_age_s and (int(time.time()) - int(q.get("ts", 0))) > max_age_s:
        return None
    return q


def _record_from_poll(r: dict):
    """Ubah satu record poller → dict quote standar, atau None."""
    if not r or not r.get("ok"):
        return None
    q = r.get("quote") or {}
    sym = str(q.get("symbol", "")).split(":")[-1].upper()
    if not sym:
        return None
    return sym, {
        "last": q.get("last"), "close": q.get("close"), "open": q.get("open"),
        "high": q.get("high"), "low": q.get("low"), "volume": q.get("volume"),
        "ts": r.get("ts") or int(time.time()), "source": "tradingview_delayed",
    }


def poll_symbols_now(tickers: list) -> dict:
    """Poll daftar simbol SPESIFIK sekarang (on-demand), tanpa gate jam bursa.

    Dipakai Funnel mode live untuk saham yang belum ada di cache. Dibatasi
    MAX_ONDEMAND. Pakai lock yang SAMA dgn poll terjadwal → bila poll terjadwal
    sedang jalan, on-demand di-skip (return {}) agar tak berebut chart.
    Return {TICKER: quote}. Hasil juga ditulis ke cache agar scan berikutnya hemat.
    """
    tickers = [str(t).strip().upper() for t in (tickers or []) if str(t).strip()][:MAX_ONDEMAND]
    if not tickers:
        return {}
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            logger.info("poll terjadwal sedang jalan — skip on-demand %d simbol", len(tickers))
            return {}
        if not ensure_tradingview_up():
            return {}
        records = _run_poller(tickers)
        out = {}
        for r in records:
            rec = _record_from_poll(r)
            if rec:
                out[rec[0]] = rec[1]
        if out:
            store = _read_store()
            store.setdefault("quotes", {}).update(out)
            store["updated_at"] = int(time.time())
            _atomic_write(CACHE_PATH, store)
        logger.info("on-demand poll: %d/%d simbol ok", len(out), len(tickers))
        return out
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def get_intraday_bulk(tickers: list, allow_ondemand: bool = False, max_age_s: int = 1200) -> dict:
    """Ambil quote intraday untuk banyak ticker. Pakai cache dulu; bila allow_ondemand
    dan dalam jendela koneksi, saham yang belum ter-cache di-poll on-demand (dibatasi).

    Return {TICKER: quote}. Ticker tanpa data tidak masuk dict (caller fallback yfinance).
    """
    result = {}
    missing = []
    for t in tickers:
        q = get_intraday(t, max_age_s=max_age_s)
        if q:
            result[str(t).upper()] = q
        else:
            missing.append(str(t).upper())
    if allow_ondemand and missing:
        try:
            from modules.market_hours import is_connectivity_window
            in_window = is_connectivity_window()
        except Exception:
            in_window = False
        if in_window:
            result.update(poll_symbols_now(missing))
    return result


def status() -> dict:
    """Ringkasan kondisi collector untuk endpoint diagnostik."""
    store = _read_store()
    return {
        "cdp_alive": cdp_alive(),
        "symbols": get_symbols(),
        "cached_tickers": sorted(store.get("quotes", {}).keys()),
        "updated_at": store.get("updated_at", 0),
        "age_s": int(time.time()) - int(store.get("updated_at", 0)) if store.get("updated_at") else None,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import sys
    force = "--force" in sys.argv
    print(json.dumps(poll_and_store(force=force), indent=2))
    print("--- status ---")
    print(json.dumps(status(), indent=2))
