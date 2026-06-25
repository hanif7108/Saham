"""
DSN-MUI Sharia Compliance Screening
====================================
Implementasi kriteria kuantitatif Daftar Efek Syariah (DES) dari OJK
yang berbasis Fatwa DSN-MUI No. 80/2011 dan POJK No. 35/2017.

Dua rasio utama untuk validasi independen:

  1. Rasio Total Utang Berbunga / Total Aset      ≤ 45%
  2. Rasio Pendapatan Non-Halal / Total Pendapatan ≤ 10%

Kriteria kualitatif (NEGATIVE LIST):
  - Tidak boleh produksi/distribusi: alkohol, daging haram, judi, riba
  - Tidak boleh: jasa keuangan ribawi (kecuali bank syariah), asuransi konvensional
  - Tidak boleh: hiburan/media yang haram

Catatan: yfinance TIDAK menyediakan kedua rasio ini secara langsung.
Pipeline ini melakukan APPROXIMATION:
  - Interest-bearing debt ratio ≈ totalDebt / totalAssets (dari balance sheet)
  - Non-halal income ratio ≈ tidak tersedia → ditandai "NEEDS_MANUAL_CHECK"

Sumber resmi DES: https://www.ojk.go.id/id/kanal/syariah/data-dan-statistik/daftar-efek-syariah/
"""

from typing import Dict, Optional


# Sektor yang otomatis NEGATIVE (haram dari kualitatif rule)
HARAM_SECTORS = {
    "Tobacco",
    "Casinos & Gaming",
    "Brewers",
    "Distillers & Vintners",
}

# Sektor yang BUTUH MANUAL CHECK (mixed-use, tidak otomatis halal)
GREY_SECTORS = {
    "Banks—Diversified",          # bank konvensional
    "Banks—Regional",             # bank konvensional
    "Insurance—Diversified",      # asuransi konvensional
    "Capital Markets",            # broker konvensional
}


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace(",", "")
    if s in ("", "N/A", "ERROR"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pct(x):
    if x is None:
        return None
    return x if abs(x) > 1.5 else x * 100


# ----------------------------- COMPLIANCE CHECKS ----------------------------- #

def check_debt_ratio(total_debt: Optional[float], total_assets: Optional[float]) -> Dict:
    """
    Rasio Utang Berbunga / Total Aset ≤ 45%.
    """
    debt = _to_float(total_debt)
    assets = _to_float(total_assets)
    if debt is None or assets is None or assets <= 0:
        return {"pass": None, "value": None, "reason": "Data utang/aset N/A — perlu cek manual"}
    ratio = (debt / assets) * 100
    ok = ratio <= 45
    return {
        "pass": bool(ok),
        "value": round(ratio, 2),
        "reason": f"Debt/Aset {ratio:.2f}% {'≤' if ok else '>'} 45% (DSN-MUI threshold)"
    }


def check_non_halal_income(non_halal_income_pct: Optional[float]) -> Dict:
    """
    Rasio Pendapatan Non-Halal / Total Pendapatan ≤ 10%.
    Catatan: yfinance tidak punya field ini, harus diisi manual / scraping report keuangan.
    """
    pct = _pct(_to_float(non_halal_income_pct))
    if pct is None:
        return {
            "pass": None,
            "value": None,
            "reason": "Data non-halal income N/A — perlu cek manual di laporan keuangan"
        }
    ok = pct <= 10
    return {
        "pass": bool(ok),
        "value": round(pct, 2),
        "reason": f"Non-halal income {pct:.2f}% {'≤' if ok else '>'} 10%"
    }


def check_sector_qualitative(sector: Optional[str], industry: Optional[str] = None) -> Dict:
    """
    Cek apakah sektor masuk daftar haram absolut atau grey area.
    """
    sec = (sector or "").strip()
    ind = (industry or "").strip()

    if sec in HARAM_SECTORS or ind in HARAM_SECTORS:
        return {
            "pass": False,
            "value": sec,
            "category": "HARAM",
            "reason": f"Sektor '{sec}' termasuk daftar haram (alkohol/judi/tembakau)"
        }

    if sec in GREY_SECTORS or ind in GREY_SECTORS:
        return {
            "pass": None,
            "value": sec,
            "category": "GREY",
            "reason": f"Sektor '{sec}' butuh verifikasi (mungkin mixed-use, "
                      f"contoh: bank konvensional vs syariah)"
        }

    return {
        "pass": True,
        "value": sec,
        "category": "HALAL",
        "reason": f"Sektor '{sec}' tidak masuk daftar haram"
    }


# ----------------------------- AGGREGATOR ----------------------------- #

def evaluate_dsn_mui(
    ticker: str,
    sector: Optional[str],
    industry: Optional[str] = None,
    total_debt: Optional[float] = None,
    total_assets: Optional[float] = None,
    non_halal_income_pct: Optional[float] = None
) -> Dict:
    """
    Evaluasi DSN-MUI compliance lengkap.

    Returns:
        {
          "verdict": "HALAL" | "HARAM" | "NEEDS_MANUAL_CHECK",
          "checks": {sector, debt, non_halal_income},
          "score": 0-3,
          "in_des": bool (kalau ticker di daftar resmi DES)
        }
    """
    checks = {
        "sector": check_sector_qualitative(sector, industry),
        "debt": check_debt_ratio(total_debt, total_assets),
        "non_halal_income": check_non_halal_income(non_halal_income_pct),
    }

    # Logika verdict:
    # - Kalau sektor HARAM → langsung HARAM
    # - Kalau ada check yg fail (False) → NON-COMPLIANT
    # - Kalau semua check yg ada lulus DAN ada minimal 1 check yang berhasil → HALAL
    # - Sisanya → NEEDS_MANUAL_CHECK
    sec_verdict = checks["sector"]["pass"]
    if sec_verdict is False:
        verdict = "HARAM"
    elif checks["debt"]["pass"] is False or checks["non_halal_income"]["pass"] is False:
        verdict = "NON-COMPLIANT"
    elif (checks["debt"]["pass"] is True and checks["non_halal_income"]["pass"] is True
          and checks["sector"]["pass"] is True):
        verdict = "HALAL"
    elif checks["sector"]["category"] == "GREY":
        verdict = "NEEDS_MANUAL_CHECK"
    else:
        # Sebagian data N/A — tetap berikan tentative HALAL kalau sektor HALAL
        if checks["sector"]["pass"] is True:
            verdict = "HALAL_TENTATIVE"
        else:
            verdict = "NEEDS_MANUAL_CHECK"

    score = sum(1 for c in checks.values() if c["pass"] is True)

    return {
        "ticker": ticker,
        "verdict": verdict,
        "score": int(score),
        "max_score": 3,
        "checks": checks,
    }


def is_in_des(ticker: str, des_list_path: str) -> bool:
    """Cek apakah ticker terdaftar di Daftar Efek Syariah resmi OJK."""
    import os
    if not os.path.exists(des_list_path):
        return False
    with open(des_list_path, "r", encoding="utf-8") as f:
        return ticker.upper() in [line.strip().upper() for line in f]


if __name__ == "__main__":
    import json

    print("=== TEST DSN-MUI COMPLIANCE ===")
    # Test 1: Saham ideal (tambang, debt rendah)
    r1 = evaluate_dsn_mui(
        "PTBA", sector="Energy",
        total_debt=5_000_000, total_assets=20_000_000,
        non_halal_income_pct=2
    )
    print(f"PTBA: {r1['verdict']} (score {r1['score']}/3)")
    for k, v in r1['checks'].items():
        print(f"  {k}: {v['reason']}")

    print()
    # Test 2: Bank konvensional (grey area)
    r2 = evaluate_dsn_mui("BBCA", sector="Banks—Diversified")
    print(f"BBCA: {r2['verdict']}")
    for k, v in r2['checks'].items():
        print(f"  {k}: {v['reason']}")

    print()
    # Test 3: Tobacco (haram absolut)
    r3 = evaluate_dsn_mui("HMSP", sector="Tobacco")
    print(f"HMSP: {r3['verdict']}")
    for k, v in r3['checks'].items():
        print(f"  {k}: {v['reason']}")
