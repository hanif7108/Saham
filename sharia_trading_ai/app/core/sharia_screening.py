"""
Screening Kepatuhan Syariah — Fatwa DSN-MUI (+ cross-check AAOIFI).

Tiga lapis:
  1. Keanggotaan Daftar Efek Syariah (DES/ISSI) OJK — otoritatif (IDX).
  2. Standar DSN-MUI: sektor halal + utang/aset ≤45% + pendapatan non-halal ≤10%.
  3. Cross-check AAOIFI (lebih ketat, basis market cap) — informatif.

Acuan: Fatwa DSN-MUI No. 40/2003 & 80/2011, POJK 35/2017, AAOIFI Standard 21.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import SHARIA
from app.core import sharia_standards
from app.data import provider


def screen_sharia(ticker: str, info: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    ticker = ticker.upper()
    in_des = ticker in set(provider.universe_tickers())
    if info is None:
        info = provider.get_info(ticker)

    sector = info.get("sector") or provider.sector_of(ticker)
    industry = info.get("industry")

    # --- DSN-MUI (utama untuk IDX) ---
    dsn = sharia_standards.evaluate_dsn_mui(
        ticker, sector=sector, industry=industry,
        total_debt=info.get("totalDebt"), total_assets=info.get("totalAssets"),
        non_halal_income_pct=None,  # tidak tersedia di yfinance → manual
    )
    # --- AAOIFI (cross-check, lebih ketat) ---
    aaoifi = sharia_standards.evaluate_aaoifi(
        ticker, market_cap=info.get("marketCap"), total_debt=info.get("totalDebt"),
        cash=info.get("totalCash"), short_term_investments=info.get("shortTermInvestments"),
        non_permissible_income=None, total_revenue=info.get("totalRevenue"),
        sector=sector, industry=industry,
    )

    # compliant final: DES + DSN-MUI tidak HARAM/NON-COMPLIANT
    dsn_bad = dsn["verdict"] in ("HARAM", "NON-COMPLIANT")
    compliant = in_des and not dsn_bad
    warning = in_des and (dsn["verdict"] in ("NEEDS_MANUAL_CHECK",) or aaoifi["compliant"] is False)

    # daftar check ringkas untuk UI (gabungan)
    checks: list[dict[str, Any]] = [{
        "kriteria": "Terdaftar di Daftar Efek Syariah (DES/ISSI) OJK",
        "nilai": "Ya" if in_des else "Tidak", "lolos": in_des,
        "acuan": "Fatwa DSN-MUI No. 40/2003",
    }]
    sc = dsn["checks"]["sector"]
    checks.append({"kriteria": "Sektor usaha halal", "nilai": sc["category"],
                   "lolos": sc["pass"], "acuan": "DSN-MUI kualitatif"})
    db = dsn["checks"]["debt"]
    checks.append({"kriteria": "Utang berbunga / Total Aset ≤ 45%",
                   "nilai": f"{db['value']}%" if db["value"] is not None else "n/a",
                   "lolos": db["pass"], "acuan": "DSN-MUI (POJK 35/2017)"})
    nh = dsn["checks"]["non_halal_income"]
    checks.append({"kriteria": "Pendapatan non-halal / Total ≤ 10%",
                   "nilai": f"{nh['value']}%" if nh["value"] is not None else "perlu cek laporan",
                   "lolos": nh["pass"], "acuan": "DSN-MUI"})
    ad = aaoifi["checks"]["debt_to_mcap"]
    checks.append({"kriteria": "Utang / Market Cap ≤ 30% (AAOIFI)",
                   "nilai": f"{ad['value']}%" if ad["value"] is not None else "n/a",
                   "lolos": ad["pass"], "acuan": "AAOIFI Standard 21"})

    return {
        "ticker": ticker,
        "compliant": compliant,
        "in_des": in_des,
        "warning": warning,
        "dsn_mui": {"verdict": dsn["verdict"], "score": dsn["score"], "max_score": dsn["max_score"]},
        "aaoifi": {"summary": aaoifi["summary"], "compliant": aaoifi["compliant"]},
        "checks": checks,
        "larangan_perdagangan": SHARIA.PROHIBITED_PRACTICES,
        "catatan": (
            "Transaksi mengikuti Fatwa DSN-MUI No. 80/2011: beli/jual tunai (non-margin, "
            "tanpa riba), long-only (tanpa short selling), atas efek yang dimiliki. "
            "DES OJK bersifat otoritatif; rasio AAOIFI ditampilkan sebagai cross-check yang lebih ketat."
        ),
    }


def filter_compliant(tickers: list[str]) -> list[str]:
    return [t for t in tickers if screen_sharia(t)["compliant"]]
