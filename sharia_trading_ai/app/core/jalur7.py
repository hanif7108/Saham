"""
Jalur 7% Trading Protocol — "Anatomi Serangan: 4 Sinyal Utama".

Mengikuti Blueprint Jalur 7% (sistem operasi harian) & meniru logika app lama:
4 sinyal struktur teknikal, masing-masing 0/1 (max 4):

  1. Kandang Kuda (Pijakan)  — area sideways tipis, candle rapat (energi tinggi).
  2. Breaker (Pendobrak)     — candle body solid menembus high 20 hari + volume.
  3. Shadow (Jejak Buyer)    — rejection sumbu bawah berulang di support.
  4. Swing Line (Ritme)      — MA20 menanjak & harga konsisten di atas MA20.

Plus filter konfirmasi berlapis: Tren (harga vs MA) + Momentum (RSI) + Volume.
"Sinyal terbaik = ketika Harga, Volume, Struktur mengatakan hal yang sama."
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from app.data import provider

MA = 20


def _rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    val = (100 - 100 / (1 + rs)).iloc[-1]
    return round(float(val), 2) if not pd.isna(val) else None


def _sig(name: str, label: str, passed: bool, reason: str, details: dict) -> dict[str, Any]:
    return {"nama": name, "label": label, "pass": passed, "reason": reason, "details": details}


def evaluate_jalur7(ticker: str, hist: Optional[pd.DataFrame] = None) -> dict[str, Any]:
    ticker = ticker.upper()
    df = hist if hist is not None else provider.get_history(ticker)
    if df is None or df.empty or len(df) < MA + 6:
        return {"ticker": ticker, "ok": False, "error": "data harga tidak cukup"}

    o, h, l, c, v = (df["Open"], df["High"], df["Low"], df["Close"], df["Volume"])
    sma20 = c.rolling(MA).mean()
    price = float(c.iloc[-1])
    ma20 = float(sma20.iloc[-1])
    pct_from_ma20 = round((price - ma20) / ma20 * 100, 2)

    # ---- 1. Breaker (Pendobrak) -------------------------------------------
    high_20 = float(h.iloc[-(MA + 1):-1].max())             # high 20 hari (excl. hari ini)
    o0, c0, h0, l0 = float(o.iloc[-1]), price, float(h.iloc[-1]), float(l.iloc[-1])
    rng = (h0 - l0) or 1e-9
    solid_ratio = round(abs(c0 - o0) / rng, 2)
    green = c0 >= o0
    vol_sma = float(v.tail(MA).mean()) or 1e-9
    vol_ratio = round(float(v.iloc[-1]) / vol_sma, 2)
    breakout = price > high_20
    br_pass = breakout and green and solid_ratio >= 0.5 and vol_ratio >= 1.0
    br_reason = []
    if not breakout:
        br_reason.append(f"Belum menembus high 20 hari ({price:.0f} vs {high_20:.0f})")
    if not green or solid_ratio < 0.5:
        br_reason.append("Candle merah/flat (body kurang solid)")
    if vol_ratio < 1.0:
        br_reason.append(f"Volume kurang kuat ({vol_ratio}x SMA20)")
    breaker = _sig("Breaker (Pendobrak)", "SINYAL: MASUK", br_pass,
                   " • ".join(br_reason) or f"Tembus high 20 hari, body solid, volume {vol_ratio}x",
                   {"pct_from_ma20": pct_from_ma20, "solid_ratio": solid_ratio, "vol_ratio": vol_ratio})

    # ---- 2. Kandang Kuda (Pijakan) ----------------------------------------
    last5 = df.tail(5)
    rng_5d = round((float(last5["High"].max()) - float(last5["Low"].min())) / float(last5["Close"].mean()) * 100, 2)
    body_5d = round(float((last5["Close"] - last5["Open"]).abs().mean()) / float(last5["Close"].mean()) * 100, 2)
    tight = rng_5d <= 6.0
    near = abs(pct_from_ma20) <= 3.0
    consistent = body_5d <= 2.0
    kk_pass = tight and near
    kk_reason = []
    if not tight:
        kk_reason.append(f"Rentang harga lebar ({rng_5d}%)")
    if not consistent:
        kk_reason.append("Ukuran candle terlalu fluktuatif")
    if not near:
        kk_reason.append(f"Jarak dari MA20 terlalu lebar ({pct_from_ma20}%)")
    kandang = _sig("Kandang Kuda (Pijakan)", "ENERGI: TINGGI", kk_pass,
                   " • ".join(kk_reason) or "Sideways tipis & rapat dekat MA20 — menyimpan energi",
                   {"range_5d_pct": rng_5d, "body_5d_pct": body_5d, "dist_from_ma20_pct": pct_from_ma20})

    # ---- 3. Shadow (Jejak Buyer) ------------------------------------------
    last3 = df.tail(3)
    n_rej = 0
    for _, row in last3.iterrows():
        body = abs(row["Close"] - row["Open"])
        lower = min(row["Close"], row["Open"]) - row["Low"]
        if lower >= max(body, 1e-9) * 1.0 and (row["High"] - row["Low"]) > 0:
            n_rej += 1
    sh_pass = n_rej >= 2
    shadow = _sig("Shadow (Jejak Buyer)", "SUPPORT: KUAT", sh_pass,
                  f"{n_rej} rejection sumbu bawah dalam 3 hari"
                  + ("" if sh_pass else " — belum ada penolakan berulang di support"),
                  {"n_rejections": n_rej})

    # ---- 4. Swing Line (Ritme) --------------------------------------------
    slope_5d = round((float(sma20.iloc[-1]) - float(sma20.iloc[-6])) / float(sma20.iloc[-6]) * 100, 2)
    days_above = int((c.tail(5).values > sma20.tail(5).values).sum())
    sw_pass = slope_5d > 0 and days_above >= 3
    sw_reason = []
    if slope_5d <= 0:
        sw_reason.append("Tren MA20 mendatar/menurun")
    if days_above < 3:
        sw_reason.append("Harga sering memotong ke bawah MA20")
    swing = _sig("Swing Line (Ritme)", "TREN: SEHAT", sw_pass,
                 " • ".join(sw_reason) or "MA20 menanjak & harga konsisten di atas MA20",
                 {"days_above_ma20": days_above, "ma20_slope_5d_pct": slope_5d})

    signals = {"breaker": breaker, "kandang_kuda": kandang, "shadow": shadow, "swing_line": swing}
    score = sum(1 for s in signals.values() if s["pass"])

    # ---- Filter konfirmasi berlapis (Tren + Momentum + Volume) ------------
    rsi = _rsi(c)
    konfirmasi = {
        "tren": {"ok": price > ma20, "detail": f"Harga {'di atas' if price > ma20 else 'di bawah'} MA20"},
        "momentum": {"ok": rsi is not None and rsi >= 50, "detail": f"RSI {rsi}"},
        "volume": {"ok": vol_ratio >= 1.0, "detail": f"Volume {vol_ratio}x SMA20"},
    }
    konf_count = sum(1 for k in konfirmasi.values() if k["ok"])

    if score >= 3:
        verdict = "STRUKTUR KUAT / SESUAI JALUR 7%"
    elif score == 2:
        verdict = "STRUKTUR BERKEMBANG"
    else:
        verdict = "STRUKTUR LEMAH / TIDAK SESUAI METODE JALUR 7%"

    return {
        "ticker": ticker, "ok": True,
        "score": score, "max_score": 4, "verdict": verdict,
        "signals": signals,
        "konfirmasi": konfirmasi, "konfirmasi_count": konf_count,
        "catatan": "Sinyal terbaik = saat Harga, Volume & Struktur mengatakan hal yang sama. "
                   "Aturan 2% (risiko max/transaksi) & RRR min 1:2.",
    }
