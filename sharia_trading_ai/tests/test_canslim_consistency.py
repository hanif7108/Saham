"""Regresi: Magic Number & CAN SLIM harus berbagi EPS QnQ (kasus PSAB)."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from app.config import CANSLIM
from app.core import canslim, fundamental


def _fake_fund(eps: float, roe: float = 40.0, source: str = "tradingview") -> dict:
    return {
        "ticker": "PSAB",
        "magic_score": 5,
        "fundamental_score": 5,
        "fundamental_label": "STRONG BUY",
        "source": source,
        "raw": {
            "eps_qnq": eps,
            "roa": 30.0,
            "roe": roe,
            "der": 0.15,
            "pbv": 1.1,
            "per": 3.0,
            "dividend_yield": 5.0,
            "bvps": 400.0,
            "mp": 434.0,
        },
        "tradingview": {"eps_yoy": 200.0},
        "checks": [],
    }


def test_letter_c_follows_fundamental_when_no_master():
    """Ticker di luar master_data: C wajib ikut EPS dari laporan fundamental."""
    fund = _fake_fund(2443.0)
    empty_hist = pd.DataFrame({
        "Open": [400] * 30, "High": [450] * 30, "Low": [380] * 30,
        "Close": [434] * 30, "Volume": [1_000_000] * 30,
    })
    with patch("app.core.canslim.master_data.metrics", return_value=None), \
         patch("app.core.canslim.provider.get_info", return_value={
             "fiftyTwoWeekHigh": 755.0,
             "heldPercentInstitutions": 0.0034,
             "floatShares": 75e6,
             "sharesOutstanding": 1e9,
             "sector": "Basic Materials",
         }), \
         patch("app.core.canslim.provider.get_history", return_value=empty_hist), \
         patch("app.core.canslim.provider.get_index_history", return_value=empty_hist), \
         patch("app.core.canslim.provider.get_annual_eps", return_value=None), \
         patch("app.core.canslim.provider.get_quarterly_eps", return_value=None), \
         patch("app.core.canslim.fundamental.sector_scores", return_value={}):
        out = canslim.evaluate_canslim("PSAB", fund=fund, hist=empty_hist, index_hist=empty_hist)

    c = out["letters"]["C"]
    assert c["lolos"] is True
    assert "2443" in c["nilai"]
    assert "n/a" not in c["nilai"].lower()


def test_sync_letter_c_repairs_na():
    """Guardrail sync memperbaiki C n/a bila Magic sudah punya EPS."""
    broken = {
        "letters": {
            "C": {"kriteria": "C", "nilai": "n/a", "target": ">= 25%", "lolos": None},
            "M": {"kriteria": "M", "nilai": "ok", "target": "", "lolos": True},
        },
        "canslim_score": 1,
        "evaluated": 1,
        "verdict": "BELUM MEMENUHI",
    }
    notes = canslim.sync_letter_c_from_fund(broken, _fake_fund(100.0))
    assert notes
    assert broken["letters"]["C"]["lolos"] is True
    assert broken["canslim_score"] == 2


def test_magic_and_canslim_c_same_threshold():
    """Ambang C CAN SLIM = ambang EPS Magic Number."""
    assert CANSLIM.C_QUARTERLY_EPS_GROWTH_MIN == fundamental.EPS_GROWTH_MIN


def test_get_metrics_is_public_entry():
    """API publik get_metrics harus ada (satu pintu data)."""
    assert callable(fundamental.get_metrics)


def test_yf_shape_fills_eps_from_quarterly_growth():
    """Fallback yfinance mengisi eps_growth agar C tidak kosong tanpa TV/master."""
    info = {
        "earningsQuarterlyGrowth": 0.40,  # 40%
        "returnOnAssets": 0.1,
        "returnOnEquity": 0.2,
        "debtToEquity": 30.0,
        "currentPrice": 100,
        "bookValue": 90,
    }
    m = fundamental._yf_shape("FAKE", info)
    assert m["eps_growth"] == 40.0
    assert m["source"] == "yfinance"
