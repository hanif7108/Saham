"""
Screening Syariah Standar — DSN-MUI & AAOIFI (port dari app produksi Mac Mini).

DSN-MUI (Indonesia, basis Total Aset) — Fatwa No. 80/2011 & POJK No. 35/2017:
  1. Utang berbunga / Total Aset      <= 45%
  2. Pendapatan non-halal / Total Pdptn <= 10%
  3. Sektor usaha halal (bukan alkohol/judi/rokok/riba)

AAOIFI (global, basis Market Cap, lebih ketat) — Shariah Standard No. 21:
  1. Utang berbunga / Market Cap        <= 30%
  2. (Kas + investasi bunga) / Market Cap <= 30%
  3. Pendapatan non-permissible / Revenue <= 5%
"""

from __future__ import annotations

from typing import Any, Optional

# ---------- daftar sektor (yfinance industry/sector style) ----------
HARAM_SECTORS = {"Tobacco", "Casinos & Gaming", "Brewers", "Distillers & Vintners"}
GREY_SECTORS = {"Banks—Diversified", "Banks—Regional", "Insurance—Diversified", "Capital Markets"}

HARAM_SECTORS_US = {
    "Banks—Diversified", "Banks—Regional", "Capital Markets", "Credit Services",
    "Financial Conglomerates", "Insurance—Diversified", "Insurance—Life",
    "Insurance—Property & Casualty", "Mortgage Finance", "Tobacco",
    "Beverages—Wineries & Distilleries", "Beverages—Brewers", "Casinos & Gaming",
    "Resorts & Casinos", "Gambling",
}
GREY_SECTORS_US = {"Aerospace & Defense", "Entertainment", "Media—Diversified"}


def _f(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace(",", "")
    if s in ("", "N/A", "ERROR", "nan", "NaN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pct(x):
    return None if x is None else (x if abs(x) > 1.5 else x * 100)


def _ratio(num, den, limit, label) -> dict[str, Any]:
    n, d = _f(num), _f(den)
    if n is None or d is None or d <= 0:
        return {"pass": None, "value": None, "reason": f"Data {label} N/A — perlu cek manual"}
    r = round(n / d * 100, 2)
    return {"pass": r <= limit, "value": r,
            "reason": f"{label} {r}% {'≤' if r <= limit else '>'} {limit}%"}


# ===================== DSN-MUI =====================
def check_sector(sector: Optional[str], industry: Optional[str]) -> dict[str, Any]:
    sec, ind = (sector or "").strip(), (industry or "").strip()
    if sec in HARAM_SECTORS or ind in HARAM_SECTORS:
        return {"pass": False, "value": sec or ind, "category": "HARAM",
                "reason": f"Sektor '{ind or sec}' termasuk daftar haram (alkohol/judi/rokok)"}
    if sec in GREY_SECTORS or ind in GREY_SECTORS:
        return {"pass": None, "value": sec or ind, "category": "GREY",
                "reason": f"Sektor '{ind or sec}' butuh verifikasi (mis. bank konvensional vs syariah)"}
    return {"pass": True, "value": sec, "category": "HALAL", "reason": f"Sektor '{sec}' tidak masuk daftar haram"}


def evaluate_dsn_mui(ticker: str, sector=None, industry=None, total_debt=None,
                     total_assets=None, non_halal_income_pct=None) -> dict[str, Any]:
    checks = {
        "sector": check_sector(sector, industry),
        "debt": _ratio(total_debt, total_assets, 45, "Utang berbunga / Total Aset"),
        "non_halal_income": (_ratio(_pct(_f(non_halal_income_pct)), 100, 10, "Pendapatan non-halal")
                             if non_halal_income_pct is not None
                             else {"pass": None, "value": None,
                                   "reason": "Pendapatan non-halal N/A — verifikasi laporan keuangan"}),
    }
    s = checks["sector"]
    if s["pass"] is False:
        verdict = "HARAM"
    elif checks["debt"]["pass"] is False or checks["non_halal_income"]["pass"] is False:
        verdict = "NON-COMPLIANT"
    elif checks["debt"]["pass"] and checks["non_halal_income"]["pass"] and s["pass"]:
        verdict = "HALAL"
    elif s["category"] == "GREY":
        verdict = "NEEDS_MANUAL_CHECK"
    else:
        verdict = "HALAL_TENTATIVE" if s["pass"] else "NEEDS_MANUAL_CHECK"
    return {"ticker": ticker, "standar": "DSN-MUI", "verdict": verdict,
            "score": sum(1 for c in checks.values() if c["pass"] is True),
            "max_score": 3, "checks": checks}


# ===================== AAOIFI =====================
def check_sector_aaoifi(sector: Optional[str], industry: Optional[str]) -> dict[str, Any]:
    combined = f"{(sector or '').strip()} {(industry or '').strip()}".lower()
    sec = (industry or sector or "").strip()
    for h in HARAM_SECTORS_US:
        if h.lower() in combined:
            return {"pass": False, "value": sec, "reason": f"'{h}' di negative list AAOIFI"}
    for kw in ("bank", "insurance", "casino", "gambling", "tobacco", "brewery",
               "winery", "distillery", "mortgage"):
        if kw in combined:
            return {"pass": None, "value": sec, "reason": f"Kata kunci '{kw}' — review manual"}
    for g in GREY_SECTORS_US:
        if g.lower() in combined:
            return {"pass": None, "value": sec, "reason": f"'{g}' grey-zone — review manual"}
    return {"pass": True, "value": sec, "reason": f"Sektor '{sec}' OK"}


def evaluate_aaoifi(ticker: str, market_cap=None, total_debt=None, cash=None,
                    short_term_investments=None, non_permissible_income=None,
                    total_revenue=None, sector=None, industry=None) -> dict[str, Any]:
    cash_total = (_f(cash) or 0) + (_f(short_term_investments) or 0)
    checks = {
        "sector": check_sector_aaoifi(sector, industry),
        "debt_to_mcap": _ratio(total_debt, market_cap, 30, "Utang berbunga / Market Cap"),
        "cash_to_mcap": (_ratio(cash_total, market_cap, 30, "Kas+invest bunga / Market Cap")
                         if (cash is not None or short_term_investments is not None)
                         else {"pass": None, "value": None, "reason": "Data kas N/A"}),
        "non_permissible": (_ratio(non_permissible_income, total_revenue, 5, "Pendapatan non-halal / Revenue")
                            if non_permissible_income is not None
                            else {"pass": None, "value": None, "reason": "Data pendapatan non-halal N/A"}),
    }
    fails = [c for c in checks.values() if c["pass"] is False]
    nones = [c for c in checks.values() if c["pass"] is None]
    if fails:
        compliant, summary = False, "FAIL"
    elif nones:
        compliant, summary = None, "NEEDS_AUDIT"
    else:
        compliant, summary = True, "PASS"
    return {"ticker": ticker, "standar": "AAOIFI", "compliant": compliant,
            "summary": summary, "checks": checks}
