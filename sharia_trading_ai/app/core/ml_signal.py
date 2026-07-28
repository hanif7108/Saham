"""
Sinyal ML (LightGBM) di atas pipeline rule-based — lapisan prediksi terukur.

Model dilatih offline (app/ml/train.py, walk-forward validated) dan dimuat
dari artifact app/ml/artifacts/. Modul ini HANYA membaca artifact; kalau
artifact tidak ada, library tidak terpasang, atau data historis kurang,
semua fungsi mengembalikan hasil "tidak tersedia" dan pipeline rule-based
jalan seperti biasa (fallback aman untuk production).

Mode (settings.ml_signal_mode):
- "off"    : modul tidak dipanggil sama sekali.
- "shadow" : prediksi ML ditampilkan di ranking/dashboard sebagai informasi,
             tidak mengubah keputusan (default — untuk membangun track record).
- "active" : ML confident ikut menggerakkan keputusan watchlist
             (veto entry saat SELL confident, kandidat BUY saat BUY confident);
             selain itu tetap rule-based.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from app.config import BASE_DIR, settings

ARTIFACT_DIR = BASE_DIR / "ml" / "artifacts"

MIN_BARS = 280   # butuh SMA200 + rolling 252 hari yang terisi

_LOCK = threading.Lock()
# horizon -> {"mtime": float, "bundle": {engine, model, meta} | None}
_CACHE: dict[int, dict] = {}


def _horizon() -> int:
    return int(getattr(settings, "ml_horizon", 5) or 5)


def mode() -> str:
    m = (getattr(settings, "ml_signal_mode", "shadow") or "shadow").lower()
    return m if m in ("off", "shadow", "active") else "shadow"


def _load(horizon: int, variant: str = "") -> Optional[dict]:
    """Muat artifact (variant mis. "_screened"), cache per proses; reload
    otomatis bila file berubah (retrain bulanan tanpa restart uvicorn)."""
    key = f"{horizon}{variant}"
    meta_path = ARTIFACT_DIR / f"ml_signal_h{horizon}{variant}.meta.json"
    try:
        mtime = meta_path.stat().st_mtime
    except OSError:
        mtime = -1.0
    cached = _CACHE.get(key)
    if cached is not None and cached["mtime"] == mtime:
        return cached["bundle"]
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached["mtime"] == mtime:
            return cached["bundle"]
        loaded = None
        try:
            meta = json.loads(meta_path.read_text())
            model_path = ARTIFACT_DIR / meta["model_file"]
            if meta.get("engine") == "lightgbm":
                import lightgbm as lgb
                model = lgb.Booster(model_file=str(model_path))
            else:
                import joblib
                model = joblib.load(model_path)
            loaded = {"engine": meta["engine"], "model": model, "meta": meta}
        except Exception:
            loaded = None
        _CACHE[key] = {"mtime": mtime, "bundle": loaded}
        return loaded


def available(horizon: Optional[int] = None) -> bool:
    return _load(horizon or _horizon()) is not None


def reset_cache() -> None:
    """Untuk test / setelah retrain in-place."""
    with _LOCK:
        _CACHE.clear()


def predict(ticker: str, hist: Optional[pd.DataFrame] = None,
            index_hist: Optional[pd.DataFrame] = None,
            variant: str = "") -> dict[str, Any]:
    """Prediksi sinyal ML untuk satu ticker dari OHLCV runtime.

    Return selalu dict; kunci "available" False bila model/data tak siap.
    """
    horizon = _horizon()
    base: dict[str, Any] = {"available": False, "horizon": horizon, "mode": mode()}
    if mode() == "off":
        return {**base, "reason": "ml_signal_mode=off"}

    bundle = _load(horizon, variant)
    if bundle is None and variant:
        bundle = _load(horizon)          # fallback ke model global
    if bundle is None:
        return {**base, "reason": "artifact tidak tersedia"}
    base["variant"] = (bundle.get("meta") or {}).get("variant", "global")

    from app.data import provider
    if provider.is_us_ticker(ticker):
        return {**base, "reason": "model dilatih untuk saham IDX saja"}

    try:
        if hist is None:
            hist = provider.get_history(ticker)
        if index_hist is None:
            index_hist = provider.get_index_history()
    except Exception:
        return {**base, "reason": "gagal memuat data harga"}

    if hist is None or len(hist) < MIN_BARS or index_hist is None or index_hist.empty:
        return {**base, "reason": f"data historis kurang (butuh >= {MIN_BARS} bar)"}

    from app.ml.features import FEATURE_COLUMNS, build_features
    try:
        hist = hist.copy()
        hist.index = pd.to_datetime(hist.index)
        if getattr(hist.index, "tz", None) is not None:
            hist.index = hist.index.tz_localize(None)
        hist.index = hist.index.normalize()
        mkt = index_hist.copy()
        mkt.index = pd.to_datetime(mkt.index)
        if getattr(mkt.index, "tz", None) is not None:
            mkt.index = mkt.index.tz_localize(None)
        mkt.index = mkt.index.normalize()

        feats = build_features(hist, mkt)
        row = feats.iloc[[-1]]
        if row[["rsi14", "close_sma200", "dist_high52w"]].isna().any(axis=None):
            return {**base, "reason": "fitur belum lengkap (rolling window)"}

        meta = bundle["meta"]
        if bundle["engine"] == "lightgbm":
            proba = bundle["model"].predict(row[FEATURE_COLUMNS])[0]
        else:
            proba = bundle["model"].predict_proba(row[FEATURE_COLUMNS])[0]
    except Exception as e:
        return {**base, "reason": f"gagal menghitung fitur/prediksi: {e}"}

    p_sell, p_hold, p_buy = (float(p) for p in proba)
    classes = ["SELL", "HOLD", "BUY"]
    idx = int(max(range(3), key=lambda i: proba[i]))
    signal = classes[idx]
    # Prioritas ambang: manual (.env) > kalibrasi realisasi (tracker) > meta model
    conf_thr = float(getattr(settings, "ml_conf_threshold", 0) or 0)
    conf_source = "manual"
    if not conf_thr:
        try:
            from app.ml import tracker
            cal = tracker.calibrated_threshold()
        except Exception:
            cal = None
        if cal:
            conf_thr, conf_source = float(cal), "kalibrasi-realisasi"
        else:
            conf_thr, conf_source = float(meta.get("conf_threshold", 0.45)), "meta-model"
    confident = signal != "HOLD" and float(proba[idx]) >= conf_thr

    # Fitur paling berpengaruh (global, dari training) + nilai saat ini,
    # bahan lapisan LLM untuk menjelaskan sinyal tanpa mengarang angka.
    top_feats = []
    for name, imp in list(meta.get("feature_importance", {}).items())[:6]:
        val = row.iloc[0].get(name)
        top_feats.append({"feature": name, "importance": imp,
                          "value": None if pd.isna(val) else round(float(val), 4)})

    return {
        "available": True,
        "mode": mode(),
        "variant": base.get("variant", "global"),
        "signal": signal,
        "confident": confident,
        "p_buy": round(p_buy, 3),
        "p_hold": round(p_hold, 3),
        "p_sell": round(p_sell, 3),
        "confidence": round(float(proba[idx]), 3),
        "conf_threshold": conf_thr,
        "conf_source": conf_source,
        "horizon": horizon,
        "label_threshold": meta.get("label_threshold"),
        "trained_at": meta.get("trained_at"),
        "as_of": str(feats.index[-1].date()),
        "top_features": top_feats,
    }


_SCAN_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_SCAN_TTL = 900          # detik — selaras cache funnel (data harian, tak perlu lebih segar)
_SCAN_LOCK = threading.Lock()


def scan_universe(force: bool = False, hist_ttl: int = 14400) -> dict[str, Any]:
    """Prediksi ML seluruh universe IDX, urut P(BUY) tertinggi (untuk dashboard).

    Memakai cache history provider (TTL 4 jam, sudah hangat setelah funnel
    jalan) + cache hasil 15 menit, jadi murah dipanggil berulang dari UI.
    """
    import time as _time
    now = _time.time()
    if not force and _SCAN_CACHE["data"] is not None and now - _SCAN_CACHE["ts"] < _SCAN_TTL:
        return _SCAN_CACHE["data"]
    with _SCAN_LOCK:
        now = _time.time()
        if not force and _SCAN_CACHE["data"] is not None and now - _SCAN_CACHE["ts"] < _SCAN_TTL:
            return _SCAN_CACHE["data"]

        base = {"mode": mode(), "horizon": _horizon(),
                "available": available(), "signals": []}
        if mode() == "off" or not base["available"]:
            _SCAN_CACHE.update(ts=now, data=base)
            return base

        from concurrent.futures import ThreadPoolExecutor
        from app.data import provider

        names = {r["ticker"]: r.get("name") for r in provider.get_universe()}
        tickers = [t for t in provider.universe_tickers()
                   if not provider.is_us_ticker(t)]
        index_hist = provider.get_index_history()

        def one(tk):
            try:
                hist = provider.get_history(tk, ttl=hist_ttl)
                r = predict(tk, hist=hist, index_hist=index_hist)
                if not r.get("available"):
                    return None
                price = float(hist["Close"].iloc[-1]) if hist is not None and len(hist) else None
                return {"ticker": tk, "name": names.get(tk),
                        "signal": r["signal"], "confident": r["confident"],
                        "p_buy": r["p_buy"], "p_hold": r["p_hold"],
                        "p_sell": r["p_sell"], "confidence": r["confidence"],
                        "as_of": r["as_of"], "price": price}
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=10) as ex:
            rows = [r for r in ex.map(one, tickers) if r]

        rows.sort(key=lambda r: r["p_buy"], reverse=True)
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        data = {**base, "signals": rows,
                "n": len(rows),
                "as_of": rows[0]["as_of"] if rows else None,
                "generated_at": _dt.now(_ZI("Asia/Jakarta")).isoformat(timespec="seconds")}
        _SCAN_CACHE.update(ts=_time.time(), data=data)
        return data


_FOCUS_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}


def focus_top10(force: bool = False) -> dict[str, Any]:
    """Alur dua tahap: screening konvensional (funnel skor) pilih top-10,
    lalu model ML varian screened menilai masing-masing.

    Tahap 1 memakai SELURUH metoda konvensional app (6 Magic, CAN SLIM,
    teknikal, jalur7, layered scoring -> skor funnel). Tahap 2 memakai
    artifact yang dilatih khusus pada populasi hasil screening historis.
    """
    import time as _time
    now = _time.time()
    if not force and _FOCUS_CACHE["data"] is not None and now - _FOCUS_CACHE["ts"] < _SCAN_TTL:
        return _FOCUS_CACHE["data"]
    with _SCAN_LOCK:
        now = _time.time()
        if not force and _FOCUS_CACHE["data"] is not None and now - _FOCUS_CACHE["ts"] < _SCAN_TTL:
            return _FOCUS_CACHE["data"]

        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        base: dict[str, Any] = {"mode": mode(), "horizon": _horizon(), "rows": [],
                                "generated_at": _dt.now(_ZI("Asia/Jakarta")).isoformat(timespec="seconds")}
        if mode() == "off":
            _FOCUS_CACHE.update(ts=now, data=base)
            return base
        try:
            from app.core import decisions
            from app.data import provider
            ranking = decisions.build_ranking()
            idx_rows = [r for r in ranking if not provider.is_us_ticker(r["ticker"])]
            top10 = sorted(idx_rows, key=lambda r: float(r.get("skor") or 0),
                           reverse=True)[:10]
            index_hist = provider.get_index_history()
            rows = []
            for i, r in enumerate(top10, 1):
                tk = r["ticker"]
                ml = predict(tk, index_hist=index_hist, variant="_screened")
                buyish = (r.get("final_signal") or "") in (
                    "STRONG BUY", "BUY", "SPECULATIVE BUY", "ACCUMULATE")
                agree = None
                if ml.get("available"):
                    agree = (ml["signal"] == "BUY") == buyish if (buyish or ml["signal"] != "HOLD") else None
                rows.append({
                    "rank": i, "ticker": tk, "name": r.get("name"),
                    "skor_funnel": r.get("skor"), "final_signal": r.get("final_signal"),
                    "keputusan": r.get("keputusan"), "price": r.get("current_price"),
                    "ml": summary_for_ranking(ml),
                    "ml_variant": ml.get("variant"),
                    "agree": agree,
                })
            base["rows"] = rows
        except Exception as e:
            base["error"] = str(e)[:200]
        _FOCUS_CACHE.update(ts=_time.time(), data=base)
        return base


def summary_for_ranking(ml: dict[str, Any]) -> dict[str, Any]:
    """Subset ringkas untuk item ranking / API dashboard."""
    if not ml.get("available"):
        return {"available": False, "reason": ml.get("reason")}
    return {k: ml[k] for k in (
        "available", "signal", "confident", "p_buy", "p_hold", "p_sell",
        "confidence", "horizon", "as_of") if k in ml}
