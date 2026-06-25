"""Endpoint analisa — laporan funnel lengkap & per-modul."""

from __future__ import annotations

from fastapi import APIRouter

from app.core import canslim, fundamental, funnel, jalur7, technical

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/analyze/{ticker}")
def analyze(ticker: str):
    """Laporan lengkap: syariah + fundamental + CAN SLIM + teknikal + rekomendasi."""
    return funnel.analyze_stock(ticker)


@router.get("/fundamental/{ticker}")
def fundamental_view(ticker: str):
    """6 Magic Number."""
    return fundamental.evaluate_fundamental(ticker)


@router.get("/canslim/{ticker}")
def canslim_view(ticker: str):
    """Skor CAN SLIM (7 kriteria)."""
    return canslim.evaluate_canslim(ticker)


@router.get("/technical/{ticker}")
def technical_view(ticker: str):
    """Analisa teknikal & sinyal entry."""
    return technical.analyze_technical(ticker)


@router.get("/chart/{ticker}")
def chart_view(ticker: str):
    """Data OHLCV + indikator untuk grafik candlestick."""
    return technical.chart_data(ticker)


@router.get("/jalur7/{ticker}")
def jalur7_view(ticker: str):
    """Jalur 7% — 4 sinyal struktur (breaker/kandang-kuda/shadow/swing-line)."""
    return jalur7.evaluate_jalur7(ticker)
