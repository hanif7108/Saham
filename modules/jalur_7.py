"""
Jalur 7% Pattern Detection Module
=================================
Mendeteksi 4 sinyal utama Jalur 7%:
  1. Breaker (Breakout Lilin Solid + Volume Tinggi)
  2. Kandang Kuda (Konsolidasi Rentang Sempit + Volume Stabil)
  3. Shadow (Rejection Sumbu Bawah Berulang / Defending Support)
  4. Swing Line (Gelombang Tren Naik Sehat di atas MA20)
"""

from typing import Dict, List, Optional
import pandas as pd
import numpy as np


def evaluate_jalur7(df: pd.DataFrame) -> Dict:
    """
    Evaluasi 4 pola utama Jalur 7% berdasarkan data historis.
    
    Args:
        df: DataFrame yfinance dengan kolom 'Open', 'High', 'Low', 'Close', 'Volume'.
        
    Returns:
        dict berisi hasil analisis:
            - score: int (0..4)
            - signals: dict status masing-masing sinyal (pass, reason, details)
            - verdict: str ringkasan sinyal
    """
    default_res = {
        "score": 0,
        "signals": {
            "breaker": {"pass": False, "reason": "Data tidak mencukupi"},
            "kandang_kuda": {"pass": False, "reason": "Data tidak mencukupi"},
            "shadow": {"pass": False, "reason": "Data tidak mencukupi"},
            "swing_line": {"pass": False, "reason": "Data tidak mencukupi"}
        },
        "verdict": "Wait & See (No Data)"
    }
    
    if df is None or df.empty or len(df) < 25:
        return default_res

    # Pastikan data diurutkan berdasarkan tanggal
    df = df.copy().sort_index()
    
    # Konversi kolom ke float untuk menghindari tipe data object
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
            
    close = df["Close"]
    open_p = df["Open"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # Hitung MA20 & Volume SMA20
    ma20 = close.rolling(window=20).mean()
    vol_sma20 = volume.rolling(window=20).mean()

    last_close = float(close.iloc[-1])
    last_open = float(open_p.iloc[-1])
    last_high = float(high.iloc[-1])
    last_low = float(low.iloc[-1])
    last_vol = float(volume.iloc[-1])
    
    last_ma20 = float(ma20.iloc[-1])
    last_vol_sma20 = float(vol_sma20.iloc[-1])

    signals = {}
    score = 0

    # ---------------- Sinyal 1: Breaker (Breakout Solid) ---------------- #
    # Kriteria:
    # 1. Close hari ini > High tertinggi 20 hari sebelumnya.
    # 2. Candle hijau & solid: body (Close - Open) >= 60% dari total range (High - Low).
    # 3. Volume > 1.3x rata-rata volume 20 hari.
    # 4. Tidak parabolic: Close / MA20 <= 1.15 (tidak naik terlalu jauh dari rata-rata).
    
    prev_20_high = float(high.iloc[-21:-1].max()) if len(df) >= 21 else 999999999
    body_size = last_close - last_open
    total_range = last_high - last_low
    is_green = body_size > 0
    
    is_solid = is_green and (total_range > 0 and (body_size / total_range) >= 0.6)
    is_breakout = last_close > prev_20_high
    is_vol_high = last_vol_sma20 > 0 and (last_vol / last_vol_sma20) > 1.3
    not_parabolic = last_ma20 > 0 and (last_close / last_ma20) <= 1.15

    breaker_pass = bool(is_breakout and is_solid and is_vol_high and not_parabolic)
    breaker_reasons = []
    if is_breakout:
        breaker_reasons.append("Breakout 20-day high")
    else:
        breaker_reasons.append(f"Belum menembus high 20 hari ({last_close:.0f} vs {prev_20_high:.0f})")
    
    if is_solid:
        breaker_reasons.append("Body solid hijau")
    elif is_green:
        breaker_reasons.append("Body hijau tapi sumbu panjang")
    else:
        breaker_reasons.append("Candle merah/flat")
        
    if is_vol_high:
        breaker_reasons.append(f"Volume tinggi ({last_vol/last_vol_sma20:.1f}x SMA20)")
    else:
        breaker_reasons.append(f"Volume kurang kuat ({last_vol/last_vol_sma20 if last_vol_sma20 > 0 else 0:.1f}x SMA20)")
        
    if not not_parabolic:
        breaker_reasons.append("Parabolik (terlalu jauh dari MA20)")

    signals["breaker"] = {
        "pass": breaker_pass,
        "reason": " • ".join(breaker_reasons),
        "details": {
            "vol_ratio": round(last_vol / last_vol_sma20, 2) if last_vol_sma20 > 0 else 0,
            "pct_from_ma20": round((last_close - last_ma20) / last_ma20 * 100, 2) if last_ma20 > 0 else 0,
            "solid_ratio": round(body_size / total_range, 2) if total_range > 0 else 0
        }
    }
    if breaker_pass:
        score += 1


    # ---------------- Sinyal 2: Kandang Kuda (Konsolidasi Sempit) ---------------- #
    # Kriteria:
    # 1. Rentang harga High-Low 5 hari terakhir sangat sempit (<= 4% dari harga saat ini).
    # 2. Rata-rata body candle 5 hari terakhir kecil (<= 1.5% dari harga).
    # 3. Volume stabil (0.4x - 1.6x rata-rata 20 hari).
    # 4. Harga dekat dengan MA20 (jarak <= 3%).
    
    recent_5_high = high.iloc[-5:].max()
    recent_5_low = low.iloc[-5:].min()
    recent_5_range_pct = (recent_5_high - recent_5_low) / last_close * 100
    
    recent_5_bodies_mean = (close.iloc[-5:] - open_p.iloc[-5:]).abs().mean()
    recent_5_body_pct = (recent_5_bodies_mean / last_close) * 100
    
    recent_5_vols = volume.iloc[-5:]
    vols_stable = True
    for v in recent_5_vols:
        ratio = v / last_vol_sma20 if last_vol_sma20 > 0 else 0
        if ratio < 0.4 or ratio > 1.7:
            vols_stable = False
            break
            
    near_ma20 = last_ma20 > 0 and (abs(last_close - last_ma20) / last_ma20 * 100) <= 3.0
    
    kuda_pass = bool(recent_5_range_pct <= 4.0 and recent_5_body_pct <= 1.5 and vols_stable and near_ma20)
    kuda_reasons = []
    
    if recent_5_range_pct <= 4.0:
        kuda_reasons.append(f"Rentang harga 5 hari sangat ketat ({recent_5_range_pct:.1f}%)")
    else:
        kuda_reasons.append(f"Rentang harga lebar ({recent_5_range_pct:.1f}%)")
        
    if recent_5_body_pct <= 1.5:
        kuda_reasons.append("Ukuran body candle kecil/sideways")
    else:
        kuda_reasons.append("Ukuran candle terlalu fluktuatif")
        
    if vols_stable:
        kuda_reasons.append("Volume transaksi stabil (tanpa lonjakan/kematian transaksi)")
    else:
        kuda_reasons.append("Volume tidak stabil")
        
    if near_ma20:
        kuda_reasons.append("Konsolidasi tepat di atas/dekat MA20")
    else:
        kuda_reasons.append("Jarak dari MA20 terlalu lebar")

    signals["kandang_kuda"] = {
        "pass": kuda_pass,
        "reason": " • ".join(kuda_reasons),
        "details": {
            "range_5d_pct": round(recent_5_range_pct, 2),
            "body_5d_pct": round(recent_5_body_pct, 2),
            "dist_from_ma20_pct": round(abs(last_close - last_ma20) / last_ma20 * 100, 2) if last_ma20 > 0 else 0
        }
    }
    if kuda_pass:
        score += 1


    # ---------------- Sinyal 3: Shadow (Defending Rejection) ---------------- #
    # Kriteria:
    # 1. Dalam 3 hari terakhir, terdapat minimal 2 candle dengan sumbu bawah (lower shadow) yang panjang.
    #    (Lower shadow >= 40% dari range harian dan >= 1.5x body candle).
    # 2. Low dari hari-hari penolakan tersebut mirip (selisih <= 1.5%), membentuk support level yang jelas.
    # 3. Volume hari penolakan cukup aktif (>= 0.8x SMA20) - bukan volume mati.
    
    shadow_days = []
    for offset in range(1, 4):  # cek 3 hari terakhir
        idx = -offset
        c_val = float(close.iloc[idx])
        o_val = float(open_p.iloc[idx])
        h_val = float(high.iloc[idx])
        l_val = float(low.iloc[idx])
        v_val = float(volume.iloc[idx])
        v_sma = float(vol_sma20.iloc[idx])
        
        lower_shadow = min(o_val, c_val) - l_val
        body = abs(c_val - o_val)
        rng = h_val - l_val
        
        is_long_wick = rng > 0 and (lower_shadow / rng >= 0.4) and (lower_shadow >= 1.5 * body)
        is_vol_active = v_sma > 0 and (v_val / v_sma) >= 0.8
        
        if is_long_wick and is_vol_active:
            shadow_days.append(l_val)
            
    shadow_pass = False
    shadow_reasons = []
    
    if len(shadow_days) >= 2:
        # Cek apakah Low-nya berada di area support yang mirip
        spread = (max(shadow_days) - min(shadow_days)) / min(shadow_days) * 100
        if spread <= 1.5:
            shadow_pass = True
            shadow_reasons.append(f"Penolakan harga bawah (lower shadow) berulang di support Rp {min(shadow_days):,.0f} (spread {spread:.1f}%)")
        else:
            shadow_reasons.append(f"Rejection lower shadow ditemukan tapi sebaran Low terlalu lebar ({spread:.1f}%)")
    else:
        shadow_reasons.append("Tidak ada rejection sumbu bawah berulang (lower shadow) dalam 3 hari terakhir")

    signals["shadow"] = {
        "pass": shadow_pass,
        "reason": " • ".join(shadow_reasons) if shadow_reasons else "Tidak terdeteksi",
        "details": {
            "n_rejections": len(shadow_days),
            "support_level": round(min(shadow_days), 2) if shadow_days else None,
            "spread_pct": round((max(shadow_days) - min(shadow_days)) / min(shadow_days) * 100, 2) if len(shadow_days) >= 2 else 0
        }
    }
    if shadow_pass:
        score += 1


    # ---------------- Sinyal 4: Swing Line (Tren Naik Sehat) ---------------- #
    # Kriteria:
    # 1. EMA atau SMA 20 mengarah ke atas (MA20 hari ini > MA20 5 hari lalu).
    # 2. Harga Close berada di atas MA20 secara konsisten (minimal 4 dari 5 hari terakhir).
    # 3. Kenaikan MA20 stabil, tidak terlalu curam (e.g. kenaikan MA20 dalam 5 hari terakhir <= 10% agar tidak FOMO).
    
    prev_ma20_5d = float(ma20.iloc[-5]) if len(df) >= 25 else 0
    ma20_upward = last_ma20 > prev_ma20_5d
    
    consist_above = sum(1 for idx in range(-5, 0) if close.iloc[idx] > ma20.iloc[idx]) >= 4
    
    ma20_slope_pct = (last_ma20 - prev_ma20_5d) / prev_ma20_5d * 100 if prev_ma20_5d > 0 else 0
    slope_healthy = ma20_slope_pct > 0 and ma20_slope_pct <= 10.0
    
    swing_pass = bool(ma20_upward and consist_above and slope_healthy)
    swing_reasons = []
    
    if ma20_upward:
        swing_reasons.append(f"Tren MA20 mengarah ke atas ({ma20_slope_pct:+.1f}% dalam 5 hari)")
    else:
        swing_reasons.append("Tren MA20 mendatar atau menurun")
        
    if consist_above:
        swing_reasons.append("Harga stabil berada di atas garis support MA20")
    else:
        swing_reasons.append("Harga sering memotong ke bawah MA20")
        
    if not slope_healthy and ma20_upward:
        swing_reasons.append("Kenaikan tren terlalu curam/liar (parabolik)")

    signals["swing_line"] = {
        "pass": swing_pass,
        "reason": " • ".join(swing_reasons),
        "details": {
            "ma20_slope_5d_pct": round(ma20_slope_pct, 2),
            "days_above_ma20": int(sum(1 for idx in range(-5, 0) if close.iloc[idx] > ma20.iloc[idx]))
        }
    }
    if swing_pass:
        score += 1

    # ---------------- Verdict ---------------- #
    if score >= 3:
        verdict = "STRUKTUR JALUR 7% SANGAT KUAT (Mulai Akumulasi / Buy)"
    elif score == 2:
        verdict = "KONSOLIDASI JALUR 7% SEHAT (Pantau / Hold)"
    elif score == 1:
        verdict = "ADA SINYAL PARSIAL (Wait & See)"
    else:
        verdict = "STRUKTUR LEMAH / TIDAK SESUAI METODE JALUR 7%"

    return {
        "score": int(score),
        "max_score": 4,
        "signals": signals,
        "verdict": verdict
    }
