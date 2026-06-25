"""
CAN SLIM Lengkap — William O'Neil + Doddy Eka Putra adaptation
==============================================================
Implementasi 7 huruf CAN SLIM secara terpisah dan terukur:

  C — Current Quarterly Earnings   > 25% YoY
  A — Annual Earnings               increase 3 tahun berturut, growth ≥ 20%/yr
  N — New Product/Mgmt/52W High     harga ≥ 85% dari 52-week high
  S — Supply & Demand               volume spike + free float < 50%
  L — Leader vs Laggard             ranking 1-3 di sektornya
  I — Institutional Sponsorship     held by funds (heldPercentInstitutions)
  M — Market Direction              IHSG > MA50 (uptrend)

Output: dict per huruf (lulus/tidak lulus + alasan), plus skor total CAN SLIM (0-7).
"""

from typing import Dict, List, Optional

import pandas as pd


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace("x", "").replace(",", "")
    if s in ("", "N/A", "ERROR", "NaN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pct(x):
    """Normalize: kalau < 1.5 → kalikan 100 (decimal), else apa adanya."""
    if x is None:
        return None
    return x if abs(x) > 1.5 else x * 100


# ---------------- C: Current Quarterly Earnings ---------------- #

def check_C(eps_growth_qnq) -> Dict:
    eps = _pct(_to_float(eps_growth_qnq))
    if eps is None:
        return {"pass": False, "value": None, "reason": "EPS QnQ N/A"}
    ok = eps >= 25
    return {
        "pass": bool(ok),
        "value": round(eps, 2),
        "reason": f"EPS QnQ {eps:.1f}% {'≥' if ok else '<'} 25%"
    }


# ---------------- A: Annual Earnings ---------------- #

def check_A(annual_growth_3y_avg=None, annual_eps_increasing=None) -> Dict:
    """
    Evaluasi annual earnings. Idealnya butuh 3 tahun data EPS.
    Karena master data biasanya cuma 1 angka, pakai approximation:
      - kalau tidak ada data 3-yr → check earnings revenue growth dari yfinance.
      - threshold: avg growth 3 tahun ≥ 20%.
    """
    growth = _pct(_to_float(annual_growth_3y_avg))
    if growth is None:
        return {"pass": False, "value": None, "reason": "Annual EPS data N/A (butuh 3 tahun)"}
    ok = growth >= 20
    return {
        "pass": bool(ok),
        "value": round(growth, 2),
        "reason": f"Annual EPS growth {growth:.1f}% {'≥' if ok else '<'} 20%"
    }


# ---------------- N: New high / 52-week high ---------------- #

def check_N(current_price, high_52w) -> Dict:
    cp = _to_float(current_price)
    hi = _to_float(high_52w)
    if cp is None or hi is None or hi <= 0:
        return {"pass": False, "value": None, "reason": "52W high data N/A"}
    pct_of_high = cp / hi * 100
    ok = pct_of_high >= 85
    return {
        "pass": bool(ok),
        "value": round(pct_of_high, 2),
        "reason": f"Harga {pct_of_high:.1f}% dari 52W high {'(near high)' if ok else '(belum dekat high)'}"
    }


# ---------------- S: Supply & Demand ---------------- #

def check_S(volume_spike, free_float_pct) -> Dict:
    vs = _to_float(volume_spike)
    ff = _pct(_to_float(free_float_pct))
    reasons = []
    pass_volume = vs is not None and vs >= 1.5
    pass_float = ff is not None and ff < 50

    if pass_volume:
        reasons.append(f"Vol spike {vs:.1f}x ≥ 1.5x")
    elif vs is not None:
        reasons.append(f"Vol spike {vs:.1f}x < 1.5x")

    if pass_float:
        reasons.append(f"Free Float {ff:.1f}% < 50%")
    elif ff is not None:
        reasons.append(f"Free Float {ff:.1f}% ≥ 50%")

    return {
        "pass": bool(pass_volume and pass_float),
        "value": {"volume_spike": vs, "free_float": ff},
        "reason": " | ".join(reasons) or "data N/A"
    }


# ---------------- L: Leader vs Laggard ---------------- #

def check_L(ticker: str, sector: str, all_stocks: List[Dict]) -> Dict:
    """
    Cari ranking ticker di sektornya. Top 3 = LEADER.
    """
    if not all_stocks or not sector or sector == "N/A":
        return {"pass": False, "value": None, "reason": "data sektor N/A"}

    # Filter sektor sama
    sector_stocks = [
        s for s in all_stocks
        if s.get("sector") == sector
    ]
    if not sector_stocks:
        return {"pass": False, "value": None, "reason": f"sektor {sector} kosong"}

    # Sort by fundamental score (desc)
    sector_stocks.sort(key=lambda s: s.get("fundamental_score", 0), reverse=True)

    # Cari rank
    rank = None
    for i, s in enumerate(sector_stocks, 1):
        if s.get("ticker") == ticker:
            rank = i
            break

    if rank is None:
        return {"pass": False, "value": None, "reason": "tidak ditemukan di sektor"}

    n = len(sector_stocks)
    is_leader = rank <= 3
    return {
        "pass": bool(is_leader),
        "value": {"rank": rank, "n_in_sector": n},
        "reason": f"Rank #{rank} dari {n} di sektor {sector} {'(LEADER)' if is_leader else '(Laggard)'}"
    }


# ---------------- I: Institutional Sponsorship ---------------- #

def check_I(held_percent_institutions) -> Dict:
    """
    yfinance: heldPercentInstitutions
    Threshold sederhana: > 1% institusional ownership = ada sponsorship.
    Untuk IDX angka ini sering kecil (<5%) karena banyak dimiliki holding/founder.
    """
    held = _pct(_to_float(held_percent_institutions))
    if held is None:
        return {"pass": False, "value": None, "reason": "Institutional ownership N/A"}
    ok = held >= 1.0
    return {
        "pass": bool(ok),
        "value": round(held, 2),
        "reason": f"Institutional {held:.2f}% {'≥' if ok else '<'} 1%"
    }


# ---------------- M: Market Direction (IHSG) ---------------- #

def check_M(ihsg_close=None, ihsg_ma50=None) -> Dict:
    """
    M: IHSG di atas MA50 = Uptrend = boleh buy.
    Caller harus pass IHSG close + MA50.
    """
    cp = _to_float(ihsg_close)
    ma = _to_float(ihsg_ma50)
    if cp is None or ma is None:
        return {"pass": False, "value": None, "reason": "IHSG/MA50 data N/A"}
    ok = cp > ma
    delta_pct = (cp - ma) / ma * 100
    return {
        "pass": bool(ok),
        "value": {"ihsg": cp, "ma50": ma, "delta_pct": round(delta_pct, 2)},
        "reason": f"IHSG {cp:.0f} {'>' if ok else '≤'} MA50 {ma:.0f} ({delta_pct:+.2f}%) — {'UPTREND' if ok else 'DOWNTREND'}"
    }


# ---------------- AGGREGATOR ---------------- #

def evaluate_canslim(
    ticker: str,
    metrics: Dict,
    sector: str,
    all_stocks: List[Dict],
    market_status: Optional[Dict] = None
) -> Dict:
    """
    Hitung skor CAN SLIM lengkap.

    Args:
        metrics: dict berisi eps_growth, annual_growth_3y, current_price, high_52w,
                 volume_spike, free_float, held_percent_institutions
        sector: sektor saham
        all_stocks: semua saham (untuk ranking L)
        market_status: dict {"ihsg_close":, "ihsg_ma50":}
    """
    market_status = market_status or {}
    results = {
        "C": check_C(metrics.get("eps_growth")),
        "A": check_A(metrics.get("annual_growth_3y_avg")),
        "N": check_N(metrics.get("current_price"), metrics.get("high_52w")),
        "S": check_S(metrics.get("volume_spike"), metrics.get("free_float")),
        "L": check_L(ticker, sector, all_stocks),
        "I": check_I(metrics.get("held_percent_institutions")),
        "M": check_M(market_status.get("ihsg_close"), market_status.get("ihsg_ma50")),
    }
    score = sum(1 for r in results.values() if r["pass"])
    return {
        "score": int(score),
        "max_score": 7,
        "pass_count": int(score),
        "letters": results,
        "stars": "⭐" * min(5, round(score / 7 * 5)) if score > 0 else "❓",
        "label": ("ALL SET" if score == 7
                  else "STRONG" if score >= 5
                  else "DECENT" if score >= 3
                  else "WEAK")
    }


# ---------------- IHSG Helper ---------------- #

def get_ihsg_status(cache_obj) -> Dict:
    """
    Ambil IHSG (^JKSE) dari cache, hitung MA50.
    Return dict siap pakai untuk check_M.
    """
    try:
        df = cache_obj.get_history("^JKSE", period="6mo", ttl_minutes=120) if hasattr(cache_obj, "get_history") else None
        if df is None:
            # Fallback langsung yfinance
            import yfinance as yf
            df = yf.Ticker("^JKSE").history(period="6mo", auto_adjust=False)
        if df is None or df.empty or "Close" not in df.columns:
            return {"ihsg_close": None, "ihsg_ma50": None}

        close = df["Close"].astype(float)
        last = float(close.iloc[-1])
        ma50 = float(close.rolling(50).mean().iloc[-1])
        return {"ihsg_close": last, "ihsg_ma50": ma50}
    except Exception as e:
        return {"ihsg_close": None, "ihsg_ma50": None, "error": str(e)}


if __name__ == "__main__":
    import json
    print("=== TEST CAN SLIM ===")
    sample_stocks = [
        {"ticker": "JPFA", "sector": "Consumer Defensive", "fundamental_score": 6},
        {"ticker": "INDF", "sector": "Consumer Defensive", "fundamental_score": 4},
        {"ticker": "ICBP", "sector": "Consumer Defensive", "fundamental_score": 3},
    ]
    result = evaluate_canslim(
        "JPFA",
        {
            "eps_growth": "30%",
            "annual_growth_3y_avg": "25%",
            "current_price": 1800,
            "high_52w": 2000,
            "volume_spike": 2.5,
            "free_float": "30%",
            "held_percent_institutions": "5%",
        },
        "Consumer Defensive",
        sample_stocks,
        market_status={"ihsg_close": 7000, "ihsg_ma50": 6800}
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
