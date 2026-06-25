"""
CAN SLIM — diselaraskan dengan app lama (Mac Mini) + modul Doddy Eka Putra.

  C  EPS QnQ >= 25%                     (dari master data)
  A  Annual EPS growth 3thn >= 20%      (yfinance, sering N/A)
  N  Harga >= 85% dari 52W high         (yfinance)
  S  Volume spike >= 1.5x DAN free float < 50%   (yfinance + master data)
  L  Rank <= 3 di sektor (by fundamental score)  (master data)
  I  Institutional >= 1%                (yfinance)
  M  IHSG > MA50 (uptrend)              (yfinance ^JKSE)
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from app.config import CANSLIM
from app.core import fundamental
from app.data import master_data, provider


def _letter(name: str, value: str, passed: Optional[bool], target: str) -> dict[str, Any]:
    return {"kriteria": name, "nilai": value, "target": target, "lolos": passed}


def _pct_norm(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return v * 100 if abs(v) <= 1 else v


def evaluate_canslim(
    ticker: str,
    info: Optional[dict[str, Any]] = None,
    hist: Optional[pd.DataFrame] = None,
    index_hist: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    ticker = ticker.upper()
    md = master_data.metrics(ticker)
    info = info if info is not None else provider.get_info(ticker)
    hist = hist if hist is not None else provider.get_history(ticker)
    index_hist = index_hist if index_hist is not None else provider.get_index_history()

    letters: dict[str, dict[str, Any]] = {}

    # ---- C : EPS QnQ >= 25% (master data) ----------------------------------
    eps_q = md["eps_growth"] if md else None
    if eps_q is None:
        qeps = provider.get_quarterly_eps(ticker)
        if qeps is not None and len(qeps) >= 5 and float(qeps.iloc[-5]) != 0:
            eps_q = round((float(qeps.iloc[-1]) - float(qeps.iloc[-5])) / abs(float(qeps.iloc[-5])) * 100, 2)
    letters["C"] = _letter("Current Earning Quarterly (EPS QnQ)",
                            f"{eps_q}%" if eps_q is not None else "n/a",
                            (eps_q >= CANSLIM.C_QUARTERLY_EPS_GROWTH_MIN) if eps_q is not None else None,
                            f">= {CANSLIM.C_QUARTERLY_EPS_GROWTH_MIN}%")

    # ---- A : Annual EPS growth 3thn >= 20% (yfinance) ----------------------
    aeps = provider.get_annual_eps(ticker)
    a_growth = None
    if aeps is not None and len(aeps) >= 2:
        vals = list(aeps.values)
        g = [(float(vals[-i]) - float(vals[-i - 1])) / abs(float(vals[-i - 1])) * 100
             for i in range(1, min(len(vals), CANSLIM.A_YEARS + 1)) if float(vals[-i - 1]) != 0]
        if g:
            a_growth = round(sum(g) / len(g), 2)
    letters["A"] = _letter("Annual Earning growth (3 thn)",
                           f"{a_growth}%" if a_growth is not None else "n/a (butuh 3 thn)",
                           (a_growth >= CANSLIM.A_ANNUAL_EPS_GROWTH_MIN) if a_growth is not None else None,
                           f">= {CANSLIM.A_ANNUAL_EPS_GROWTH_MIN}%")

    # ---- N : Harga >= 85% dari 52W high ------------------------------------
    n_pass, n_detail = None, "n/a"
    high_52w = info.get("fiftyTwoWeekHigh")
    last = (md["market_price"] if md and md.get("market_price") else None)
    if hist is not None and not hist.empty:
        if not high_52w:
            high_52w = float(hist["High"].tail(252).max())
        if last is None:
            last = float(hist["Close"].iloc[-1])
    if high_52w and last and high_52w > 0:
        pct = last / float(high_52w) * 100
        n_pass = pct >= CANSLIM.N_NEAR_HIGH_PCT
        n_detail = f"{pct:.1f}% dari 52W high"
    letters["N"] = _letter("New High / dekat 52W high", n_detail, n_pass,
                           f">= {CANSLIM.N_NEAR_HIGH_PCT}%")

    # ---- S : Volume spike >= 1.5x DAN free float < 50% ---------------------
    vol_spike = None
    if hist is not None and not hist.empty and len(hist) >= 20:
        vavg = float(hist["Volume"].tail(20).mean()) or 1e-9
        vol_spike = round(float(hist["Volume"].iloc[-1]) / vavg, 2)
    free_float = md["free_float"] if md else _ff_from_info(info)
    s_vol = vol_spike is not None and vol_spike >= CANSLIM.S_VOLUME_SPIKE_MULT
    s_ff = free_float is not None and free_float < CANSLIM.S_FREE_FLOAT_MAX_PCT
    s_parts = []
    if vol_spike is not None:
        s_parts.append(f"Vol {vol_spike}x {'≥' if s_vol else '<'} 1.5x")
    if free_float is not None:
        s_parts.append(f"FF {free_float}% {'<' if s_ff else '≥'} 50%")
    letters["S"] = _letter("Supply & Demand (volume + free float)",
                           " | ".join(s_parts) or "n/a",
                           bool(s_vol and s_ff) if (vol_spike is not None or free_float is not None) else None,
                           "volume ≥ 1.5x & free float < 50%")

    # ---- L : Rank <= 3 di sektor (by fundamental score) --------------------
    sector = (md["sector"] if md else None) or provider.sector_of(ticker)
    l_pass, l_detail = None, "n/a"
    if sector and sector not in ("N/A", ""):
        scores = fundamental.sector_scores()
        peers = [(t, scores.get(t, 0)) for t in master_data.tickers()
                 if master_data.sector_of(t) == sector]
        peers.sort(key=lambda x: x[1], reverse=True)
        rank = next((i for i, (t, _) in enumerate(peers, 1) if t == ticker), None)
        if rank:
            l_pass = rank <= CANSLIM.L_TOP_RANK
            l_detail = f"Rank #{rank}/{len(peers)} sektor {sector}"
    letters["L"] = _letter("Leader (rank sektor)", l_detail, l_pass,
                           f"rank <= {CANSLIM.L_TOP_RANK}")

    # ---- I : Institutional >= 1% -------------------------------------------
    inst = _pct_norm(info.get("heldPercentInstitutions"))
    letters["I"] = _letter("Institutional Sponsorship",
                           f"{round(inst, 2)}%" if inst is not None else "n/a",
                           (inst >= CANSLIM.I_INSTITUTION_MIN_PCT) if inst is not None else None,
                           f">= {CANSLIM.I_INSTITUTION_MIN_PCT}%")

    # ---- M : IHSG > MA50 ----------------------------------------------------
    m_pass, m_detail = None, "n/a"
    p = CANSLIM.M_MA_PERIOD
    if index_hist is not None and len(index_hist) >= p:
        ihsg = float(index_hist["Close"].iloc[-1])
        ma = float(index_hist["Close"].rolling(p).mean().iloc[-1])
        m_pass = ihsg > ma
        m_detail = f"IHSG {ihsg:.0f} {'>' if m_pass else '≤'} MA{p} {ma:.0f}"
    letters["M"] = _letter(f"Market Direction (IHSG vs MA{p})", m_detail, m_pass,
                           f"IHSG di atas MA{p}")

    passed = sum(1 for v in letters.values() if v["lolos"] is True)
    evaluated = sum(1 for v in letters.values() if v["lolos"] is not None)
    return {
        "ticker": ticker, "canslim_score": passed, "canslim_total": 7,
        "evaluated": evaluated, "letters": letters, "verdict": _verdict(passed, evaluated),
    }


def _ff_from_info(info: dict[str, Any]) -> Optional[float]:
    fs, so = info.get("floatShares"), info.get("sharesOutstanding")
    return round(fs / so * 100, 1) if (fs and so) else None


def _verdict(score: int, evaluated: int) -> str:
    if evaluated == 0:
        return "DATA TIDAK CUKUP"
    if score >= 6:
        return "KANDIDAT KUAT"
    if score >= 4:
        return "LAYAK PANTAU"
    return "BELUM MEMENUHI"
