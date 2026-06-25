"""Endpoint Screener Saham Undervalue (model multi-faktor + backtest historis)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core import undervalue

router = APIRouter(prefix="/api/undervalue", tags=["undervalue"])


@router.get("/screen")
def screen(top: int = 6, max_pbv: float | None = None,
           min_score: float = 55.0, horizon: int = undervalue.HORIZON_DAYS,
           target_pct: float = undervalue.TARGET_PCT, scan_limit: int | None = None):
    """Pindai SELURUH saham syariah → Top-N aksi KUAT (BUY belum dimiliki / SELL dimiliki).

    - `top`       : jumlah aksi kuat ditampilkan (default 6).
    - `max_pbv`   : saring hanya PBV ≤ nilai ini.
    - `min_score` : ambang skor agar dianggap BUY kuat (default 55).
    - `horizon`   : horizon backtest (hari bursa).
    - `target_pct`: ambang "menang" backtest (%).
    - `scan_limit`: HANYA untuk uji cepat (batasi jumlah dipindai). Default = semua.
    """
    return undervalue.screen(top=top, max_pbv=max_pbv, min_score=min_score,
                             horizon=horizon, target_pct=target_pct, scan_limit=scan_limit)


@router.get("/analyze/{ticker}")
def analyze(ticker: str, horizon: int = undervalue.HORIZON_DAYS,
            target_pct: float = undervalue.TARGET_PCT):
    """Detail skor undervalue + backtest + rencana trading untuk satu saham."""
    r = undervalue.evaluate(ticker, horizon=horizon, target_pct=target_pct)
    if not r:
        raise HTTPException(status_code=404, detail=f"{ticker.upper()} tidak ada di master data syariah.")
    return r
