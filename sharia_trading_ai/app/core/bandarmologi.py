"""
Analisis Bandarmologi & Smart Money (Prioritas 3).
Mendeteksi apakah saham sedang diakumulasi (dibeli besar-besaran) atau didistribusikan
(dijual) oleh bandar/institusi/smart money sebelum keputusan BELI diambil.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import httpx

from app.config import CACHE_DIR, settings
from app.data import provider


def calculate_cmf(df: pd.DataFrame, period: int = 10) -> Optional[float]:
    """Menghitung Chaikin Money Flow (CMF) harian sebagai proxy aliran akumulasi/distribusi."""
    if len(df) < period:
        return None
    
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    volume = df["Volume"]
    
    # Close Location Value (CLV): Nilai posisi penutupan relatif terhadap range High-Low
    # Rentang: -1 (tutup di Low ekstrem) s/d +1 (tutup di High ekstrem)
    denom = (high - low).replace(0, np.nan)
    clv = ((close - low) - (high - close)) / denom
    clv = clv.fillna(0.0)
    
    # Money Flow Volume (Volume aliran dana)
    mfv = clv * volume
    
    # Akumulasi 10 hari
    mfv_sum = mfv.rolling(period).sum()
    vol_sum = volume.rolling(period).sum()
    
    cmf = mfv_sum / vol_sum.replace(0, np.nan)
    cmf_val = cmf.iloc[-1]
    
    return float(cmf_val) if not np.isnan(cmf_val) else None


def get_bandar_analysis(ticker: str, hist: Optional[pd.DataFrame] = None) -> dict[str, Any]:
    """Mendapatkan hasil analisa Bandarmologi (Smart Money/Foreign/Broker Flow)."""
    ticker = ticker.upper()
    prov = settings.bandarmologi_provider or "volatility_proxy"
    
    # 1. OPSI: Membaca cache lokal jika disediakan
    if prov == "local_cache":
        cache_file = CACHE_DIR / "broker_summary.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                if ticker in data:
                    res = data[ticker]
                    # Harus mengembalikan format standar layak_beli
                    res.setdefault("layak_beli", res.get("sentiment") not in ("DISTRIBUSI", "DISTRIBUSI BESAR"))
                    res.setdefault("provider", "local_cache")
                    return res
            except Exception:  # noqa: BLE001
                pass
        # Jika gagal/kosong, fallback ke proxy
        prov = "volatility_proxy"
        
    # 2. OPSI: Meminta ke API eksternal jika dikonfigurasi
    if prov == "api" and settings.bandarmologi_api_url:
        try:
            headers = {}
            if settings.bandarmologi_api_key:
                headers["Authorization"] = f"Bearer {settings.bandarmologi_api_key}"
            r = httpx.get(f"{settings.bandarmologi_api_url}?ticker={ticker}", headers=headers, timeout=5)
            if r.status_code == 200:
                res = r.json()
                res.setdefault("layak_beli", res.get("sentiment") not in ("DISTRIBUSI", "DISTRIBUSI BESAR"))
                res.setdefault("provider", "api")
                return res
        except Exception:  # noqa: BLE001
            pass
        # Jika gagal, fallback ke proxy
        prov = "volatility_proxy"

    # 3. OPSI DEFAULT: Volatility Proxy (Kombinasi CMF + VPT harian)
    df = hist if hist is not None else provider.get_history(ticker)
    if df is None or df.empty or len(df) < 15:
        return {
            "ticker": ticker, "provider": "volatility_proxy", "sentiment": "NETRAL",
            "score": 50.0, "net_flow_estimation": 0, "cmf": 0.0, "layak_beli": True,
            "note": "Data transaksi tidak cukup untuk analisa Bandarmologi."
        }
        
    cmf_val = calculate_cmf(df)
    
    # Estimasi Net Flow sederhana untuk visualisasi (volume penutupan * perubahan harga * CMF)
    close = df["Close"]
    volume = df["Volume"]
    if len(close) >= 2 and cmf_val is not None:
        price_diff = float(close.iloc[-1] - close.iloc[-2])
        net_flow = int(volume.iloc[-1] * price_diff * cmf_val)
    else:
        net_flow = 0
        
    # Klasifikasi sentiment berdasarkan CMF
    if cmf_val is None:
        sentiment = "NETRAL"
        score = 50.0
    elif cmf_val >= 0.15:
        sentiment = "AKUMULASI BESAR"
        score = round((cmf_val + 1.0) * 50.0, 1)
    elif cmf_val >= 0.03:
        sentiment = "AKUMULASI"
        score = round((cmf_val + 1.0) * 50.0, 1)
    elif cmf_val <= -0.15:
        sentiment = "DISTRIBUSI BESAR"
        score = round((cmf_val + 1.0) * 50.0, 1)
    elif cmf_val <= -0.03:
        sentiment = "DISTRIBUSI"
        score = round((cmf_val + 1.0) * 50.0, 1)
    else:
        sentiment = "NETRAL"
        score = 50.0
        
    # Gerbang penyaring akhir: tidak boleh dalam posisi distribusi
    layak_beli = sentiment not in ("DISTRIBUSI", "DISTRIBUSI BESAR")
    
    return {
        "ticker": ticker,
        "provider": "volatility_proxy",
        "sentiment": sentiment,
        "score": score,
        "net_flow_estimation": net_flow,
        "cmf": round(cmf_val, 3) if cmf_val is not None else 0.0,
        "layak_beli": layak_beli,
        "note": f"Dihitung berbasis hubungan volume-harga (Chaikin Money Flow: {cmf_val:.3f})" if cmf_val is not None else "Deteksi volume mendatar."
    }
