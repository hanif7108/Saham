"""
Narasi AI Terjadwal (Claude API)
================================
Menghasilkan ringkasan analisis singkat (Bahasa Indonesia) per holding saat jam
bursa, di-cache untuk disajikan web app. Dijalankan terjadwal — BUKAN per-request
(panggilan LLM mahal & lambat; tidak boleh di jalur request multi-perangkat).

Konteks per saham = data intraday TradingView (delayed) + sinyal teknikal yfinance
(compute_signals). Murah & deterministik di sisi data; LLM hanya merangkai narasi.

Degradasi mulus: tanpa ANTHROPIC_API_KEY atau SDK, modul nonaktif diam-diam dan
web app tetap jalan tanpa narasi.

Model default claude-opus-4-8 (override via ANTHROPIC_MODEL). Biaya API per panggilan
— karena itu lingkupnya dibatasi holding + cadence lambat.
"""

import fcntl
import json
import logging
import os
import time

logger = logging.getLogger("sharia.ai_narrative")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(BASE_DIR, "cache", "ai_narrative.json")
LOCK_PATH = os.path.join(BASE_DIR, "cache", "ai_narrative.lock")
PORTFOLIO_PATH = os.path.join(BASE_DIR, "portfolio.csv")

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
MAX_TICKERS = int(os.environ.get("AI_NARRATIVE_MAX_TICKERS", "3"))

SYSTEM_PROMPT = (
    "Anda analis saham syariah Indonesia. Diberi data teknikal satu saham IDX, "
    "tulis narasi ringkas (maksimal 3 kalimat, Bahasa Indonesia) untuk investor ritel: "
    "kondisi terkini, momentum, dan satu hal yang perlu diperhatikan. "
    "Jangan beri ajakan beli/jual eksplisit. Gunakan angka dari data, jangan mengarang. "
    "Akhiri dengan disclaimer singkat: 'Bukan rekomendasi.'"
)


def _have_key() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    # fallback: baca .env bila proses tidak memuatnya
    try:
        with open(os.path.join(BASE_DIR, ".env")) as f:
            for ln in f:
                if ln.strip().startswith("ANTHROPIC_API_KEY="):
                    val = ln.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        os.environ["ANTHROPIC_API_KEY"] = val
                        return True
    except FileNotFoundError:
        pass
    return False


def _client():
    import anthropic  # impor lokal agar absennya SDK tidak mematikan import modul
    return anthropic.Anthropic()


# ----------------------------- Konteks per saham ----------------------------- #
def _build_context(ticker: str) -> dict:
    from modules.cache import Cache
    from modules.technical_analysis import compute_signals
    from modules.tv_collector import get_intraday

    ctx = {"ticker": ticker}
    try:
        c = Cache(cache_dir="cache")
        df = c.get_history(ticker, period="6mo")
        sig = compute_signals(df) if df is not None else {}
        ctx["signal"] = sig.get("signal")
        ctx["rsi"] = sig.get("rsi")
        ctx["ma20"] = sig.get("ma20")
        ctx["ma50"] = sig.get("ma50")
        ctx["macd_hist"] = sig.get("macd_hist")
        ctx["volume_spike"] = sig.get("volume_spike")
        ctx["last_close_eod"] = sig.get("last_close")
    except Exception as e:
        logger.warning("gagal konteks teknikal %s: %s", ticker, e)
    iq = get_intraday(ticker)
    if iq:
        ctx["intraday"] = {k: iq.get(k) for k in ("last", "open", "high", "low", "volume")}
        ctx["intraday_source"] = "tradingview_delayed"
    return ctx


def _generate_one(client, ticker: str) -> dict:
    ctx = _build_context(ticker)
    user_msg = (
        f"Data saham {ticker} (IDX):\n{json.dumps(ctx, ensure_ascii=False)}\n\n"
        "Tulis narasinya."
    )
    # System prompt di-cache (prefix stabil) → murah saat dipanggil berulang.
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return {
        "ticker": ticker,
        "narrative": text,
        "model": MODEL,
        "generated_at": int(time.time()),
    }


# ----------------------------- Simbol ----------------------------- #
def get_symbols() -> list:
    """Holding portfolio dulu (paling relevan & murah), dibatasi MAX_TICKERS."""
    import csv
    tickers = []
    try:
        with open(PORTFOLIO_PATH) as f:
            for row in csv.DictReader(f):
                t = (row.get("Ticker") or "").strip().upper()
                if t and t not in tickers:
                    tickers.append(t)
    except FileNotFoundError:
        pass
    return tickers[:MAX_TICKERS]


# ----------------------------- Generate & store ----------------------------- #
def _read_store() -> dict:
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"narratives": {}, "updated_at": 0}


def _atomic_write(data: dict):
    import tempfile
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE_PATH), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)


def generate_and_store(force: bool = False) -> dict:
    """Satu siklus: gate jam bursa + key → generate narasi holding → cache. Lock lintas-proses."""
    from modules.market_hours import is_connectivity_window

    if not force and not is_connectivity_window():
        return {"status": "skipped_outside_window", "count": 0}
    if not _have_key():
        return {"status": "no_api_key", "count": 0}

    symbols = get_symbols()
    if not symbols:
        return {"status": "no_symbols", "count": 0}

    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            return {"status": "locked", "count": 0}

        try:
            client = _client()
        except Exception as e:
            logger.error("gagal init Anthropic client: %s", e)
            return {"status": "client_error", "error": str(e), "count": 0}

        store = _read_store()
        narr = store.setdefault("narratives", {})
        ok = 0
        for t in symbols:
            try:
                narr[t] = _generate_one(client, t)
                ok += 1
            except Exception as e:
                logger.warning("gagal narasi %s: %s", t, e)
        store["updated_at"] = int(time.time())
        _atomic_write(store)
        logger.info("AI narasi: %s/%s saham", ok, len(symbols))
        return {"status": "ok", "count": ok, "total": len(symbols)}
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


# ----------------------------- Baca (web app) ----------------------------- #
def get_narrative(ticker: str, max_age_s: int = 7200):
    t = (ticker or "").strip().upper()
    n = _read_store().get("narratives", {}).get(t)
    if not n:
        return None
    if max_age_s and (int(time.time()) - int(n.get("generated_at", 0))) > max_age_s:
        return None
    return n


def status() -> dict:
    store = _read_store()
    return {
        "enabled": _have_key(),
        "model": MODEL,
        "symbols": get_symbols(),
        "cached_tickers": sorted(store.get("narratives", {}).keys()),
        "updated_at": store.get("updated_at", 0),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import sys
    print(json.dumps(generate_and_store(force="--force" in sys.argv), indent=2, ensure_ascii=False))
    print(json.dumps(status(), indent=2, ensure_ascii=False))
