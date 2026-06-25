"""
AAOIFI Shariah Compliance Screening (US / Global Stocks)
========================================================
Implementasi kriteria kuantitatif AAOIFI Shariah Standard No. 21
yang umum dipakai untuk screening saham global (NYSE/NASDAQ),
Dow Jones Islamic Market Index, S&P Shariah Indices, Wahed HLAL ETF,
Zoya screening, dll.

Tiga rasio utama (semua basis Market Capitalization):

  1. Total interest-bearing debt / Market Cap            ≤ 30%
  2. Cash + interest-earning securities / Market Cap     ≤ 30%
  3. Non-permissible income / Total Revenue              ≤ 5%

Negative list sektor (kualitatif): conventional banking, conventional insurance,
alcohol, tobacco, gambling/casinos, pork-related, adult entertainment, weapons
(controversial), interest-based lending.

Perbedaan vs DSN-MUI (yang dipakai untuk IDX):
  • DSN-MUI: debt/aset ≤ 45%, non-halal income ≤ 10%, basis Total Asset.
  • AAOIFI : debt/marketcap ≤ 30%, non-permissible income ≤ 5%, basis Market Cap.

AAOIFI lebih ketat → universe US Sharia umumnya lebih kecil dibanding IDX
relatif terhadap total emiten yang ada di bursa.

CATATAN PENTING:
  yfinance TIDAK menyediakan breakdown "interest income" atau "non-permissible
  income" secara eksplisit. Untuk produksi yang serius, sebaiknya source dari
  Zoya API / Dow Jones Islamic / S&P Shariah (yang sudah melakukan manual
  audit). Modul ini melakukan APPROXIMATION berbasis data publik yfinance:
    - Interest-bearing debt ≈ longTermDebt + shortLongTermDebt (atau totalDebt)
    - Interest-earning investments ≈ cash + shortTermInvestments
    - Non-permissible income → tidak tersedia direct → ditandai "NEEDS_AUDIT"

Sumber:
  - AAOIFI Standard 21: https://www.oicexchanges.org/files/1---shari-ah-screening-in-the-islamic-capital-markets-dr-hamed-merah-secretary-general-aaoifi.pdf
  - Zoya methodology: https://zoya.finance/
  - HLAL ETF prospectus (Wahed FTSE USA Shariah).
"""

from __future__ import annotations

from typing import Dict, Optional


# Sektor yang OTOMATIS NEGATIVE (haram dari kualitatif rule AAOIFI).
HARAM_SECTORS_US = {
    # Conventional financial services
    "Banks—Diversified",
    "Banks—Regional",
    "Capital Markets",
    "Credit Services",
    "Financial Conglomerates",
    "Insurance—Diversified",
    "Insurance—Life",
    "Insurance—Property & Casualty",
    "Mortgage Finance",
    # Vice industries
    "Tobacco",
    "Beverages—Wineries & Distilleries",
    "Beverages—Brewers",
    "Casinos & Gaming",
    "Resorts & Casinos",
    "Gambling",
    # Adult entertainment / weapons di bawah ini umumnya tidak punya sector
    # eksplisit di yfinance; perlu manual check by ticker.
}

# Sektor "borderline" — perlu cek per-emiten (mixed-use).
GREY_SECTORS_US = {
    "Aerospace & Defense",   # weapons exposure check
    "Entertainment",          # adult content / music check
    "Media—Diversified",
}


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace("$", "").replace(",", "")
    if s in ("", "N/A", "ERROR", "NaN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ----------------------------- COMPLIANCE CHECKS ----------------------------- #

def check_debt_ratio_aaoifi(total_debt: Optional[float],
                            market_cap: Optional[float]) -> Dict:
    """
    AAOIFI: Interest-bearing debt / Market Cap ≤ 30%.
    """
    debt = _to_float(total_debt)
    mcap = _to_float(market_cap)
    if debt is None or mcap is None or mcap <= 0:
        return {"pass": None, "value": None,
                "reason": "Data debt/marketcap N/A — perlu cek manual"}
    ratio = (debt / mcap) * 100
    ok = ratio <= 30
    return {
        "pass": bool(ok),
        "value": round(ratio, 2),
        "reason": f"Debt/MCap {ratio:.2f}% {'≤' if ok else '>'} 30% (AAOIFI threshold)"
    }


def check_cash_ratio_aaoifi(cash: Optional[float],
                            short_term_investments: Optional[float],
                            market_cap: Optional[float]) -> Dict:
    """
    AAOIFI: (Cash + interest-earning short-term investments) / Market Cap ≤ 30%.
    """
    c = _to_float(cash) or 0.0
    sti = _to_float(short_term_investments) or 0.0
    mcap = _to_float(market_cap)
    if mcap is None or mcap <= 0:
        return {"pass": None, "value": None,
                "reason": "Data marketcap N/A"}
    total = c + sti
    if total == 0 and (cash is None and short_term_investments is None):
        return {"pass": None, "value": None,
                "reason": "Data cash N/A — perlu cek manual"}
    ratio = (total / mcap) * 100
    ok = ratio <= 30
    return {
        "pass": bool(ok),
        "value": round(ratio, 2),
        "reason": f"Cash+ST inv/MCap {ratio:.2f}% {'≤' if ok else '>'} 30%"
    }


def check_non_permissible_income(non_permissible_income: Optional[float],
                                 total_revenue: Optional[float]) -> Dict:
    """
    AAOIFI: Non-permissible income / Total Revenue ≤ 5%.
    yfinance tidak expose direct → biasanya manual / Zoya API.
    """
    npi = _to_float(non_permissible_income)
    rev = _to_float(total_revenue)
    if npi is None or rev is None or rev <= 0:
        return {"pass": None, "value": None,
                "reason": "Non-permissible income N/A — perlu audit Zoya/AAOIFI"}
    ratio = (npi / rev) * 100
    ok = ratio <= 5
    return {
        "pass": bool(ok),
        "value": round(ratio, 2),
        "reason": f"Non-permissible income {ratio:.2f}% {'≤' if ok else '>'} 5%"
    }


def check_sector_aaoifi(sector: Optional[str], industry: Optional[str] = None) -> Dict:
    """Cek sektor terhadap negative & grey list AAOIFI."""
    sec = (sector or "").strip()
    ind = (industry or "").strip()
    combined = (sec + " | " + ind).lower()

    # Cek HARAM
    for haram in HARAM_SECTORS_US:
        if haram.lower() in combined:
            return {"pass": False, "value": sec,
                    "reason": f"Sektor '{haram}' masuk negative list AAOIFI"}

    # Heuristik kata kunci tambahan
    bad_keywords = ["bank", "insurance", "casino", "gambling", "tobacco",
                    "brewery", "winery", "distillery", "mortgage", "interest"]
    for kw in bad_keywords:
        if kw in combined:
            # Ada kemungkinan false positive (mis. "TransUnion" mengandung "union"
            # ≠ banking). Tandai sebagai grey, bukan haram.
            return {"pass": None, "value": sec,
                    "reason": f"Kata kunci '{kw}' di sektor — review manual"}

    # Cek GREY
    for grey in GREY_SECTORS_US:
        if grey.lower() in combined:
            return {"pass": None, "value": sec,
                    "reason": f"Sektor '{grey}' grey-zone — review manual"}

    return {"pass": True, "value": sec, "reason": f"Sektor '{sec}' OK"}


# ----------------------------- AGGREGATE ----------------------------- #

def evaluate_aaoifi(ticker: str,
                    market_cap: Optional[float] = None,
                    total_debt: Optional[float] = None,
                    cash: Optional[float] = None,
                    short_term_investments: Optional[float] = None,
                    non_permissible_income: Optional[float] = None,
                    total_revenue: Optional[float] = None,
                    sector: Optional[str] = None,
                    industry: Optional[str] = None) -> Dict:
    """
    Evaluasi semua kriteria AAOIFI dan return dict ringkasan:
        {
          "ticker": "AAPL",
          "compliant": True/False/None,
          "checks": {...},
          "summary": "PASS" | "FAIL" | "NEEDS_AUDIT"
        }

    Logika compliant:
      - sektor FAIL                 → compliant=False
      - debt OR cash OR income FAIL → compliant=False
      - semua check PASS            → compliant=True
      - ada yang None (NEEDS_AUDIT) → compliant=None ("perlu audit manual")
    """
    sec_check = check_sector_aaoifi(sector, industry)
    debt_check = check_debt_ratio_aaoifi(total_debt, market_cap)
    cash_check = check_cash_ratio_aaoifi(cash, short_term_investments, market_cap)
    income_check = check_non_permissible_income(non_permissible_income, total_revenue)

    checks = {
        "sector": sec_check,
        "debt_to_mcap": debt_check,
        "cash_to_mcap": cash_check,
        "non_permissible_income": income_check,
    }

    # Aggregate verdict
    failed_any = any(c["pass"] is False for c in checks.values())
    has_unknown = any(c["pass"] is None for c in checks.values())

    if failed_any:
        compliant = False
        summary = "FAIL"
    elif has_unknown:
        compliant = None
        summary = "NEEDS_AUDIT"
    else:
        compliant = True
        summary = "PASS"

    return {
        "ticker": ticker.upper(),
        "compliant": compliant,
        "summary": summary,
        "checks": checks,
        "standard": "AAOIFI Shariah Standard No. 21",
    }


# ----------------------------- HELPER: dari yfinance info ----------------------------- #

def evaluate_from_yfinance_info(ticker: str, info: Dict) -> Dict:
    """
    Convenience wrapper: ambil yfinance .info dict, ekstrak field yang relevan,
    lalu panggil evaluate_aaoifi().

    yfinance info field mapping (approximate, beberapa field bisa null):
      - marketCap
      - totalDebt
      - totalCash, shortTermInvestments
      - totalRevenue
      - sector, industry
    """
    return evaluate_aaoifi(
        ticker=ticker,
        market_cap=info.get("marketCap"),
        total_debt=info.get("totalDebt"),
        cash=info.get("totalCash"),
        short_term_investments=info.get("shortTermInvestments"),
        non_permissible_income=None,  # Tidak ada di yfinance — selalu NEEDS_AUDIT
        total_revenue=info.get("totalRevenue"),
        sector=info.get("sector"),
        industry=info.get("industry"),
    )
