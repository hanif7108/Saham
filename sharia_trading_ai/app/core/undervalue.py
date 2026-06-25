"""
Screener Saham UNDERVALUE — model multi-faktor + validasi backtest historis.

Pendekatan "AI berbasis data historis" (transparan & dapat diaudit):

1. SKOR VALUASI (fundamental terkurasi master_data):
   kemurahan (PBV, PER, PEG, Margin of Safety / angka Graham) + kualitas
   (ROE, DER, pertumbuhan EPS) + pendapatan (dividend yield).

2. SKOR TIMING (data harga historis 2thn): RSI (oversold), posisi vs 52-pekan,
   jarak ke SMA200, momentum 20 hari, filter tren.

3. BACKTEST HISTORIS (inti "akurasi dari data"): mensimulasikan aturan entry
   mean-reversion (RSI < ambang oversold) sepanjang riwayat, mengukur WIN-RATE
   & RATA-RATA RETURN ke depan (horizon ~1 bulan). Probabilitas empiris inilah
   yang dipakai sebagai keyakinan model — dipelajari dari perilaku historis saham.

SKOR AKHIR = gabungan berbobot ketiganya → ranking + rencana trading (entry,
stop Jalur 7%, target, RRR, ekspektasi return). Narasi AI naratif disediakan
on-demand lewat advisor (Gemini/Ollama/lokal) yang sudah ada.

Hanya saham syariah-compliant (DES/ISSI + DSN-MUI) yang diloloskan.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

from app.core import portfolio, sharia_screening, technical
from app.data import master_data, provider

# --- parameter default model --- #
HORIZON_DAYS = 20        # hari bursa ke depan utk backtest (~1 bulan)
TARGET_PCT = 7.0         # ambang "menang" (sejalan Jalur 7%)
OVERSOLD_RSI = 35.0      # pemicu entry value / mean-reversion
STOP_PCT = 7.0           # cut-loss dasar (Jalur 7%)
MIN_RRR = 1.5            # risk-reward minimal
CUT_LOSS_PCT = -7.0      # SELL bila P/L ≤ -7% (selaras Decisions)
TAKE_PROFIT_PCT = 20.0   # SELL bila P/L ≥ +20%


# --------------------------- util skor --------------------------- #
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _lin(x: Optional[float], lo: float, hi: float) -> Optional[float]:
    """Map x dari [lo,hi] → [0,1]. lo→0, hi→1 (boleh lo>hi untuk arah terbalik)."""
    if x is None:
        return None
    if hi == lo:
        return 0.5
    return _clamp01((x - lo) / (hi - lo))


def _wmean(parts: dict[str, tuple[Optional[float], float]]) -> Optional[float]:
    """Rata-rata berbobot komponen yang tersedia (None/NaN diabaikan, bobot dinormalisasi)."""
    ok = {k: (v, w) for k, (v, w) in parts.items() if v is not None and not _isnan(v)}
    num = sum(v * w for v, w in ok.values())
    den = sum(w for v, w in ok.values())
    return (num / den) if den else None


def _isnan(x: Any) -> bool:
    return isinstance(x, float) and (math.isnan(x) or math.isinf(x))


def _clean(o: Any) -> Any:
    """Ganti NaN/inf → None secara rekursif agar aman di-serialize ke JSON."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(x) for x in o]
    return o


def _safe(x: Any, fallback: float) -> float:
    """Konversi ke float, NaN/None → fallback."""
    try:
        v = float(x)
        return fallback if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return fallback


# --------------------------- valuasi --------------------------- #
def _valuation(m: dict[str, Any]) -> tuple[Optional[float], list[dict], dict]:
    pbv, per, peg = m.get("pbv"), m.get("per"), m.get("peg")
    roe, der, epsg = m.get("roe"), m.get("der"), m.get("eps_growth")
    dy, bvps, mp = m.get("dividend_yield"), m.get("bvps"), m.get("market_price")

    # Margin of Safety via angka Graham = sqrt(22.5 * EPS * BVPS); EPS = MP/PER
    graham = mos = None
    if per and per > 0 and mp and bvps and bvps > 1:
        eps_abs = mp / per
        if eps_abs > 0:
            graham = math.sqrt(22.5 * eps_abs * bvps)
            mos = (graham - mp) / mp

    comps = {
        "PBV (murah)":            (_lin(pbv, 2.0, 0.6), 0.18),
        "PER (murah)":            (_lin(per, 25.0, 7.0), 0.14),
        "PEG (<1 ideal)":         (_lin(peg, 2.0, 0.5), 0.10),
        "Margin of Safety":       (_lin(mos, -0.2, 0.5), 0.13),
        "ROE (kualitas)":         (_lin(roe, 0.0, 20.0), 0.15),
        "DER (rendah=aman)":      (_lin(der, 200.0, 30.0), 0.10),
        "Pertumbuhan EPS":        (_lin(epsg, 0.0, 25.0), 0.10),
        "Dividend Yield":         (_lin(dy, 0.0, 7.0), 0.10),
    }
    score = _wmean(comps)
    factors = [{"faktor": k, "nilai01": round(v, 2) if v is not None else None, "bobot": w}
               for k, (v, w) in comps.items()]
    extra = {"graham_number": round(graham) if graham else None,
             "margin_of_safety_pct": round(mos * 100, 1) if mos is not None else None}
    return (score * 100 if score is not None else None), factors, extra


# --------------------------- timing teknikal --------------------------- #
def _timing(df: pd.DataFrame) -> tuple[Optional[float], dict]:
    close = df["Close"].dropna()
    if len(close) < 60:
        return None, {}
    price = float(close.iloc[-1])
    rsi_v = _safe(technical.rsi(close, 14).iloc[-1], 50.0)
    sma50 = technical.sma(close, 50).iloc[-1]
    sma200 = technical.sma(close, 200).iloc[-1]
    win = close.tail(252)
    hi52, lo52 = float(win.max()), float(win.min())
    pos52 = (price - lo52) / (hi52 - lo52) if hi52 > lo52 else 0.5
    prev21 = _safe(close.iloc[-21], price) if len(close) > 21 else price
    mom20 = (price / prev21 - 1) if prev21 else 0.0
    dist200 = (price / float(sma200) - 1) if pd.notna(sma200) else 0.0

    # Favor: oversold, dekat 52w-low (basing), sedikit di bawah SMA200, momentum mulai positif
    s_rsi = _lin(rsi_v, 70.0, 30.0)
    s_pos = _lin(pos52, 0.85, 0.10)
    # jarak ke SMA200: ideal ~ -8%..0; terlalu jauh di bawah (<-30%) = jatuh, dihukum
    s_dist = _clamp01(1 - abs(dist200 + 0.05) / 0.30)
    s_mom = _lin(mom20, -0.10, 0.08)
    parts = {"RSI": (s_rsi, 0.35), "Posisi 52-pekan": (s_pos, 0.25),
             "Jarak SMA200": (s_dist, 0.20), "Momentum 20h": (s_mom, 0.20)}
    score = _wmean(parts)
    info = {"price": round(price, 2), "rsi": round(rsi_v, 1),
            "pos_52w_pct": round(pos52 * 100, 1), "momentum_20d_pct": round(mom20 * 100, 2),
            "dist_sma200_pct": round(dist200 * 100, 2),
            "sma50": round(float(sma50), 2) if pd.notna(sma50) else None,
            "sma200": round(float(sma200), 2) if pd.notna(sma200) else None}
    return (score * 100 if score is not None else None), info


# --------------------------- backtest historis --------------------------- #
def _backtest(df: pd.DataFrame, horizon: int = HORIZON_DAYS,
              target: float = TARGET_PCT, oversold: float = OVERSOLD_RSI) -> dict:
    close = df["Close"].dropna().reset_index(drop=True)
    base = {"n_signals": 0, "win_rate": None, "avg_return": None, "median_return": None,
            "horizon_days": horizon, "target_pct": target, "oversold_rsi": oversold}
    if len(close) < horizon + 60:
        return base
    rsi_s = technical.rsi(close, 14)
    fwd = close.shift(-horizon) / close - 1.0

    # Entry: RSI < oversold; de-overlap minimal `horizon` hari antar sinyal
    idxs, last = [], -10 ** 9
    n = len(close)
    for i in range(n - horizon):
        r = rsi_s.iloc[i]
        if pd.notna(r) and r < oversold and (i - last) >= horizon:
            idxs.append(i)
            last = i
    rets = [float(fwd.iloc[i]) for i in idxs if pd.notna(fwd.iloc[i])]
    if not rets:
        return base
    wins = sum(1 for x in rets if x >= target / 100.0)
    rets_sorted = sorted(rets)
    med = rets_sorted[len(rets_sorted) // 2]
    return {
        "n_signals": len(rets),
        "win_rate": round(wins / len(rets) * 100, 1),
        "avg_return": round(sum(rets) / len(rets) * 100, 2),
        "median_return": round(med * 100, 2),
        "best": round(max(rets) * 100, 2),
        "worst": round(min(rets) * 100, 2),
        "horizon_days": horizon, "target_pct": target, "oversold_rsi": oversold,
    }


def _bt_confidence(bt: dict) -> Optional[float]:
    """Keyakinan empiris 0-100 dari backtest: win-rate dipotong oleh ukuran sampel."""
    if not bt or not bt.get("n_signals") or bt.get("win_rate") is None:
        return None
    sample_factor = min(1.0, bt["n_signals"] / 8.0)   # <8 sinyal → diskon
    return round(bt["win_rate"] * sample_factor, 1)


# --------------------------- rencana trading --------------------------- #
def _trade_plan(df: pd.DataFrame, price: float, bt: dict,
                target_pct: float) -> dict:
    close = df["Close"].dropna()
    swing_low = float(close.tail(20).min()) if len(close) >= 20 else price * (1 - STOP_PCT / 100)
    stop_j7 = price * (1 - STOP_PCT / 100)
    stop = max(swing_low, stop_j7)            # stop paling masuk akal (tidak lebih jauh dari J7)
    if stop >= price:
        stop = stop_j7
    risk_pct = (price - stop) / price * 100
    # target: max(ambang, ekspektasi backtest), jaga RRR minimal
    bt_avg = bt.get("avg_return") or 0
    tgt_pct = max(target_pct, bt_avg, risk_pct * MIN_RRR)
    target = price * (1 + tgt_pct / 100)
    rrr = (tgt_pct / risk_pct) if risk_pct > 0 else None
    return {
        "entry": round(price, 2),
        "stop_loss": round(stop, 2),
        "target": round(target, 2),
        "risk_pct": round(risk_pct, 2),
        "reward_pct": round(tgt_pct, 2),
        "rrr": round(rrr, 2) if rrr else None,
    }


# --------------------------- evaluasi 1 saham --------------------------- #
def _label(score: float, downtrend: bool, bt: dict) -> tuple[str, str]:
    n = bt.get("n_signals") or 0
    wr = bt.get("win_rate")
    proven = n >= 5 and wr is not None and wr >= 45     # cukup bukti historis & win-rate sehat
    if score >= 70 and not downtrend and proven:
        return "STRONG BUY", "buy"
    if score >= 55 and not downtrend:
        return "BUY", "buy"
    if score >= 45 or (score >= 55 and downtrend):       # murah tapi tren turun → pantau dulu
        return "WATCH", "warning"
    return "PASS", "hold"


def evaluate(ticker: str, horizon: int = HORIZON_DAYS,
             target_pct: float = TARGET_PCT) -> Optional[dict[str, Any]]:
    tk = ticker.upper().strip()
    m = master_data.metrics(tk)
    if not m:
        return None
    sh = sharia_screening.screen_sharia(tk)
    val_score, factors, val_extra = _valuation(m)

    df = provider.get_history(tk, period="2y")
    if df is None or df.empty or "Close" not in df:
        return None
    price = float(df["Close"].dropna().iloc[-1])
    timing_score, tinfo = _timing(df)
    bt = _backtest(df, horizon, target_pct)
    bt_conf = _bt_confidence(bt)
    bt_thin = bt_conf is None or (bt.get("n_signals") or 0) < 5
    # Tanpa bukti historis cukup → backtest dianggap RENDAH (20), bukan diabaikan.
    # Ini MENGHUKUM saham "murah tapi tak terbukti" (anti value-trap), bukan menaikkannya.
    bt_eff = bt_conf if bt_conf is not None else 20.0

    combo = _wmean({
        "valuasi": (val_score / 100 if val_score is not None else None, 0.50),
        "timing":  (timing_score / 100 if timing_score is not None else None, 0.20),
        "backtest": (bt_eff / 100, 0.30),
    })
    if combo is None or _isnan(combo):
        return None
    score = round(combo * 100, 1)

    tech_rep = technical.analyze_technical(tk, hist=df)
    downtrend = bool(tech_rep.get("trend") == "DOWNTREND")
    label, css = _label(score, downtrend, bt)
    plan = _trade_plan(df, price, bt, target_pct)

    return _clean({
        "ticker": tk, "name": m.get("name"), "sector": m.get("sector"),
        "price": round(price, 2),
        "score": score, "label": label, "css": css,
        "sharia": sh.get("compliant", False), "sharia_warning": sh.get("warning", False),
        "valuation_score": round(val_score, 1) if val_score is not None else None,
        "timing_score": round(timing_score, 1) if timing_score is not None else None,
        "backtest_confidence": bt_conf,
        "backtest_thin": bt_thin,
        "downtrend": downtrend,
        "metrics": {k: m.get(k) for k in ("pbv", "per", "peg", "roe", "der",
                                          "eps_growth", "dividend_yield")},
        "valuation_extra": val_extra,
        "timing": tinfo,
        "backtest": bt,
        "factors": factors,
        "plan": plan,
        "expected_return_pct": bt.get("avg_return"),
    })


# --------------------------- rekomendasi sadar-portofolio --------------------------- #
def _sell_conviction(c: dict, pnl: Optional[float]) -> tuple[float, list[str]]:
    """Keyakinan EXIT 0-100 untuk saham yang DIMILIKI. 0 = tidak perlu jual (HOLD)."""
    conv, reasons = 0.0, []
    if pnl is not None and pnl <= CUT_LOSS_PCT:
        conv = max(conv, 85 + min(15.0, abs(pnl) - 7))
        reasons.append(f"Cut-loss — P/L {pnl:.1f}% ≤ {CUT_LOSS_PCT}%")
    if pnl is not None and pnl >= TAKE_PROFIT_PCT:
        conv = max(conv, 75.0)
        reasons.append(f"Take-profit — P/L +{pnl:.1f}%")
    if c["score"] < 40:
        conv = max(conv, 55 + (40 - c["score"]))
        reasons.append(f"Undervalue hilang (skor {c['score']})")
    if c.get("downtrend"):
        conv = max(conv, 58.0)
        reasons.append("Tren menurun (harga < SMA50 < SMA200)")
    if c.get("sharia_warning") and not c.get("sharia"):
        conv = max(conv, 70.0)
        reasons.append("Status syariah bermasalah")
    return round(conv, 1), reasons


def _recommend(scored: list[dict], min_buy: float) -> list[dict]:
    """Bangun aksi KUAT: BUY (belum dimiliki & skor tinggi) / SELL (dimiliki & memicu exit)."""
    held = {p["ticker"]: p for p in portfolio.list_positions()["positions"]}
    recs = []
    for c in scored:
        tk = c["ticker"]
        if tk in held:
            pnl = held[tk].get("pl_pct")
            conv, reasons = _sell_conviction(c, pnl)
            if conv > 0:
                recs.append({
                    "ticker": tk, "name": c["name"], "sector": c["sector"],
                    "action": "SELL", "css": "sell", "conviction": conv,
                    "owned": True, "pnl_pct": pnl, "score": c["score"], "label": c["label"],
                    "reason": " · ".join(reasons),
                    "backtest": c["backtest"], "metrics": c["metrics"], "price": c["price"],
                    "next_step": f"Jual {tk} untuk eksekusi exit (lihat alasan).",
                })
            # dimiliki tapi sehat → HOLD, tidak masuk daftar aksi kuat
        else:
            if c["score"] >= min_buy and c["label"] in ("STRONG BUY", "BUY"):
                bt = c["backtest"]
                win = f"win {bt['win_rate']}% (n={bt['n_signals']})" if bt.get("win_rate") is not None else "backtest tipis"
                recs.append({
                    "ticker": tk, "name": c["name"], "sector": c["sector"],
                    "action": "BUY", "css": c["css"], "conviction": c["score"],
                    "owned": False, "pnl_pct": None, "score": c["score"], "label": c["label"],
                    "reason": f"Undervalue {c['label']} (skor {c['score']}) · valuasi {c['valuation_score']} · {win}",
                    "backtest": bt, "metrics": c["metrics"], "price": c["price"], "plan": c["plan"],
                    "next_step": f"Entry {c['plan']['entry']} · Stop {c['plan']['stop_loss']} · Target {c['plan']['target']} (RRR {c['plan']['rrr']}).",
                })
    recs.sort(key=lambda r: r["conviction"], reverse=True)
    return recs


# --------------------------- screener --------------------------- #
def screen(top: int = 6, max_pbv: Optional[float] = None,
           min_score: float = 55.0, horizon: int = HORIZON_DAYS,
           target_pct: float = TARGET_PCT, include_warning: bool = True,
           scan_limit: Optional[int] = None) -> dict[str, Any]:
    """Pindai SELURUH saham syariah (bukan potongan alfabetis), beri skor, lalu
    hasilkan Top-N aksi KUAT: BUY (belum dimiliki) / SELL (dimiliki & memicu exit).

    `scan_limit` hanya untuk uji cepat (membatasi jumlah dipindai); default = semua.
    """
    tickers = master_data.tickers()
    if scan_limit:
        tickers = tickers[:scan_limit]
    cands, errors = [], 0
    for tk in tickers:
        try:
            r = evaluate(tk, horizon, target_pct)
        except Exception:  # noqa: BLE001
            errors += 1
            continue
        if not r or not r["sharia"]:
            continue
        if not include_warning and r.get("sharia_warning"):
            continue
        if max_pbv is not None and (r["metrics"].get("pbv") or 1e9) > max_pbv:
            continue
        cands.append(r)
    cands.sort(key=lambda r: r["score"], reverse=True)
    recommendations = _recommend(cands, min_score)[:max(1, top)]

    return {
        "params": {"top": top, "max_pbv": max_pbv, "min_score": min_score,
                   "horizon_days": horizon, "target_pct": target_pct},
        "scanned": len(tickers), "errors": errors,
        "universe_size": len(master_data.tickers()),
        "recommendations": recommendations,
        "rec_count": len(recommendations),
        "count": len(cands), "candidates": cands,      # seluruh saham ter-ranking (transparansi)
        "metodologi": ("Memindai SELURUH saham syariah. Skor = 50% valuasi "
                       "(PBV/PER/PEG/MoS Graham + ROE/DER/EPS/DY) + 20% timing teknikal + "
                       f"30% keyakinan backtest historis (entry RSI<{OVERSOLD_RSI}, horizon {horizon}h, "
                       f"target {target_pct}%). Aksi KUAT = BUY (skor ≥ {min_score}, belum dimiliki) "
                       "atau SELL (dimiliki & memicu exit: cut-loss/overvalued/downtrend). "
                       "Advisory — bukan ajakan beli/jual."),
    }
