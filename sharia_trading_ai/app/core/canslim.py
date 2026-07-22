"""
CAN SLIM — diselaraskan dengan app lama (Mac Mini) + modul Doddy Eka Putra.

  C  EPS QnQ >= 25%                     (WAJIB sama sumber 6 Magic Number)
  A  Annual EPS growth 3thn >= 20%      (+ ROE >= 17% bila tersedia; fallback EPS YoY)
  N  Harga >= 85% dari 52W high
  S  Free float < 50% (+ volume spike atau FF sangat ketat < 25%)
  L  Rank <= 3 di sektor ATAU RS > indeks (6 bulan)
  I  Institutional >= 1%
  M  IHSG > MA50 (uptrend)

PENTING: Jangan baca master_data langsung untuk huruf C/A.
Pakai fundamental.get_metrics() / hasil evaluate_fundamental (argumen fund=).
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


def _relative_strength(
    hist: Optional[pd.DataFrame],
    index_hist: Optional[pd.DataFrame],
    lookback: int = 126,
) -> tuple[Optional[bool], str]:
    """Leader via relative strength vs indeks (~6 bulan)."""
    if hist is None or index_hist is None or hist.empty or index_hist.empty:
        return None, "n/a"
    if len(hist) < lookback or len(index_hist) < lookback:
        return None, "n/a (histori pendek)"
    s0, s1 = float(hist["Close"].iloc[-lookback]), float(hist["Close"].iloc[-1])
    i0, i1 = float(index_hist["Close"].iloc[-lookback]), float(index_hist["Close"].iloc[-1])
    if s0 <= 0 or i0 <= 0:
        return None, "n/a"
    stock_ret = (s1 / s0 - 1) * 100
    idx_ret = (i1 / i0 - 1) * 100
    rs = stock_ret - idx_ret
    passed = stock_ret > idx_ret
    return passed, f"RS 6bln {rs:+.1f}% (saham {stock_ret:+.1f}% vs idx {idx_ret:+.1f}%)"


def sync_letter_c_from_fund(cslim: dict[str, Any], fund: dict[str, Any]) -> list[str]:
    """Paksa huruf C mengikuti EPS QnQ 6 Magic Number. Kembalikan daftar koreksi."""
    notes: list[str] = []
    raw = (fund or {}).get("raw") or {}
    eps = raw.get("eps_qnq")
    if eps is None:
        return notes
    letters = cslim.setdefault("letters", {})
    c = letters.get("C") or {}
    old_pass = c.get("lolos")
    new_pass = eps >= CANSLIM.C_QUARTERLY_EPS_GROWTH_MIN
    src = fund.get("source") or "fundamental"
    letters["C"] = _letter(
        "Current Earning Quarterly (EPS QnQ)",
        f"{round(float(eps), 1)}% [{src}]",
        new_pass,
        f">= {CANSLIM.C_QUARTERLY_EPS_GROWTH_MIN}%",
    )
    if old_pass != new_pass or (c.get("nilai") or "").startswith("n/a"):
        notes.append(
            f"Huruf C diselaraskan ke 6 Magic Number (EPS QnQ {round(float(eps), 1)}% dari {src})"
        )
        # hitung ulang skor
        passed = sum(1 for v in letters.values() if v.get("lolos") is True)
        evaluated = sum(1 for v in letters.values() if v.get("lolos") is not None)
        cslim["canslim_score"] = passed
        cslim["evaluated"] = evaluated
        cslim["verdict"] = _verdict(passed, evaluated)
    return notes


def evaluate_canslim(
    ticker: str,
    info: Optional[dict[str, Any]] = None,
    hist: Optional[pd.DataFrame] = None,
    index_hist: Optional[pd.DataFrame] = None,
    *,
    fund: Optional[dict[str, Any]] = None,
    metrics: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    if ticker.endswith(".JK"):
        ticker = ticker[:-3]
    md = master_data.metrics(ticker)
    info = info if info is not None else provider.get_info(ticker)
    hist = hist if hist is not None else provider.get_history(ticker)
    index_hist = index_hist if index_hist is not None else provider.get_index_history(ticker)

    # Sumber metrik SENADA dengan 6 Magic Number
    if metrics is None and fund is not None:
        # Rekonstruksi ringan dari laporan fundamental (hindari fetch ganda)
        raw = fund.get("raw") or {}
        metrics = {
            "eps_growth": raw.get("eps_qnq"),
            "roa": raw.get("roa"),
            "roe": raw.get("roe"),
            "der": raw.get("der"),
            "pbv": raw.get("pbv"),
            "per": raw.get("per"),
            "dy": raw.get("dividend_yield"),
            "bvps": raw.get("bvps"),
            "mp": raw.get("mp"),
            "source": fund.get("source"),
            "tv_extra": fund.get("tradingview") or {},
        }
    if metrics is None:
        metrics = fundamental.get_metrics(ticker, info)
    tv_extra = metrics.get("tv_extra") or {}

    letters: dict[str, dict[str, Any]] = {}

    # ---- C : EPS QnQ — utamakan raw fundamental / get_metrics --------------
    eps_q = metrics.get("eps_growth")
    if eps_q is None and fund and (fund.get("raw") or {}).get("eps_qnq") is not None:
        eps_q = fund["raw"]["eps_qnq"]
    if eps_q is None and md:
        eps_q = md.get("eps_growth")
    if eps_q is None:
        eps_q = _pct_norm(info.get("earningsQuarterlyGrowth"))
    if eps_q is None:
        qeps = provider.get_quarterly_eps(ticker)
        if qeps is not None and len(qeps) >= 5 and float(qeps.iloc[-5]) != 0:
            eps_q = round(
                (float(qeps.iloc[-1]) - float(qeps.iloc[-5])) / abs(float(qeps.iloc[-5])) * 100, 2
            )
    src_c = metrics.get("source") or (fund or {}).get("source") or "—"
    letters["C"] = _letter(
        "Current Earning Quarterly (EPS QnQ)",
        f"{round(float(eps_q), 1)}% [{src_c}]" if eps_q is not None else "n/a",
        (eps_q >= CANSLIM.C_QUARTERLY_EPS_GROWTH_MIN) if eps_q is not None else None,
        f">= {CANSLIM.C_QUARTERLY_EPS_GROWTH_MIN}%",
    )

    # ---- A : Annual EPS growth + ROE (fallback EPS YoY) --------------------
    aeps = provider.get_annual_eps(ticker)
    a_growth = None
    a_src = "annual"
    if aeps is not None and len(aeps) >= 2:
        vals = list(aeps.values)
        g = [
            (float(vals[-i]) - float(vals[-i - 1])) / abs(float(vals[-i - 1])) * 100
            for i in range(1, min(len(vals), CANSLIM.A_YEARS + 1))
            if float(vals[-i - 1]) != 0
        ]
        if g:
            a_growth = round(sum(g) / len(g), 2)
    if a_growth is None:
        yoy = tv_extra.get("eps_yoy")
        if yoy is None:
            yoy = _pct_norm(info.get("earningsGrowth"))
        if yoy is not None:
            a_growth = round(float(yoy), 2)
            a_src = "YoY/TTM"
    roe = metrics.get("roe")
    if roe is None and md:
        roe = md.get("roe")
    growth_ok = (a_growth >= CANSLIM.A_ANNUAL_EPS_GROWTH_MIN) if a_growth is not None else None
    roe_ok = (roe >= CANSLIM.A_ROE_MIN) if roe is not None else None
    if growth_ok is None:
        a_pass = None
    elif roe_ok is None:
        a_pass = growth_ok
    else:
        a_pass = bool(growth_ok and roe_ok)
    a_parts = []
    if a_growth is not None:
        a_parts.append(f"growth {round(a_growth, 1)}% ({a_src})")
    else:
        a_parts.append("growth n/a")
    if roe is not None:
        a_parts.append(f"ROE {round(float(roe), 1)}%")
    letters["A"] = _letter(
        "Annual Earning growth + ROE",
        " · ".join(a_parts),
        a_pass,
        f"growth >= {CANSLIM.A_ANNUAL_EPS_GROWTH_MIN}% & ROE >= {CANSLIM.A_ROE_MIN}%",
    )

    # ---- N : Harga >= 85% dari 52W high ------------------------------------
    n_pass, n_detail = None, "n/a"
    high_52w = info.get("fiftyTwoWeekHigh")
    last = metrics.get("mp") or (md["market_price"] if md and md.get("market_price") else None)
    if hist is not None and not hist.empty:
        if not high_52w:
            high_52w = float(hist["High"].tail(252).max())
        if last is None:
            last = float(hist["Close"].iloc[-1])
    if high_52w and last and high_52w > 0:
        pct = last / float(high_52w) * 100
        n_pass = pct >= CANSLIM.N_NEAR_HIGH_PCT
        n_detail = f"{pct:.1f}% dari 52W high"
    letters["N"] = _letter(
        "New High / dekat 52W high", n_detail, n_pass, f">= {CANSLIM.N_NEAR_HIGH_PCT}%"
    )

    # ---- S : Free float (+ volume spike atau FF sangat ketat) --------------
    vol_spike = None
    if hist is not None and not hist.empty and len(hist) >= 20:
        vavg = float(hist["Volume"].tail(20).mean()) or 1e-9
        vol_spike = round(float(hist["Volume"].iloc[-1]) / vavg, 2)
    free_float = md["free_float"] if md else None
    if free_float is None:
        free_float = _ff_from_info(info)
    s_vol = vol_spike is not None and vol_spike >= CANSLIM.S_VOLUME_SPIKE_MULT
    s_ff = free_float is not None and free_float < CANSLIM.S_FREE_FLOAT_MAX_PCT
    s_tight = free_float is not None and free_float < 25.0
    if free_float is None and vol_spike is None:
        s_pass = None
    else:
        s_pass = bool(s_ff and (s_vol or s_tight))
    s_parts = []
    if vol_spike is not None:
        s_parts.append(f"Vol {vol_spike}x {'≥' if s_vol else '<'} 1.5x")
    if free_float is not None:
        s_parts.append(f"FF {free_float}% {'<' if s_ff else '≥'} 50%")
        if s_tight and not s_vol:
            s_parts.append("FF ketat → supply OK")
    letters["S"] = _letter(
        "Supply & Demand (free float + volume)",
        " | ".join(s_parts) or "n/a",
        s_pass,
        "free float < 50% & (volume ≥ 1.5x atau FF < 25%)",
    )

    # ---- L : Rank sektor ATAU relative strength vs indeks ------------------
    is_us = provider.is_us_ticker(ticker)
    sector = (
        (md["sector"] if md else None)
        or provider.sector_of(ticker)
        or info.get("sector")
    )
    l_pass, l_detail = None, "n/a"
    if sector and sector not in ("N/A", ""):
        scores = fundamental.sector_scores(is_us)
        peers_tickers = provider.us_universe_tickers() if is_us else master_data.tickers()
        peers = [
            (t, scores.get(t, 0))
            for t in peers_tickers
            if provider.sector_of(t) == sector
        ]
        if ticker not in {t for t, _ in peers}:
            if fund and fund.get("fundamental_score") is not None:
                own = int(fund["fundamental_score"])
            else:
                try:
                    own = fundamental.evaluate_fundamental(ticker, info=info)["fundamental_score"]
                except Exception:  # noqa: BLE001
                    own = 0
            peers.append((ticker, own))
        peers.sort(key=lambda x: x[1], reverse=True)
        rank = next((i for i, (t, _) in enumerate(peers, 1) if t == ticker), None)
        if rank:
            l_pass = rank <= CANSLIM.L_TOP_RANK
            l_detail = f"Rank #{rank}/{len(peers)} sektor {sector}"
    if l_pass is not True:
        rs_pass, rs_detail = _relative_strength(hist, index_hist)
        if rs_pass is True:
            l_pass = True
            l_detail = (l_detail + " · " if l_detail not in ("n/a",) else "") + rs_detail
        elif l_pass is None and rs_pass is not None:
            l_pass = rs_pass
            l_detail = rs_detail
        elif l_pass is False and rs_pass is False:
            l_detail = f"{l_detail} · {rs_detail}"
    letters["L"] = _letter(
        "Leader (rank sektor / RS vs indeks)",
        l_detail,
        l_pass,
        f"rank <= {CANSLIM.L_TOP_RANK} atau RS 6bln > indeks",
    )

    # ---- I : Institutional >= 1% -------------------------------------------
    inst = _pct_norm(info.get("heldPercentInstitutions"))
    letters["I"] = _letter(
        "Institutional Sponsorship",
        f"{round(inst, 2)}%" if inst is not None else "n/a",
        (inst >= CANSLIM.I_INSTITUTION_MIN_PCT) if inst is not None else None,
        f">= {CANSLIM.I_INSTITUTION_MIN_PCT}%",
    )

    # ---- M : Market Index > MA50 --------------------------------------------
    m_pass, m_detail = None, "n/a"
    p = CANSLIM.M_MA_PERIOD
    idx_name = "S&P 500" if is_us else "IHSG"
    if index_hist is not None and len(index_hist) >= p:
        idx_val = float(index_hist["Close"].iloc[-1])
        ma = float(index_hist["Close"].rolling(p).mean().iloc[-1])
        m_pass = idx_val > ma
        m_detail = f"{idx_name} {idx_val:.0f} {'>' if m_pass else '≤'} MA{p} {ma:.0f}"
    letters["M"] = _letter(
        f"Market Direction ({idx_name} vs MA{p})",
        m_detail,
        m_pass,
        f"{idx_name} di atas MA{p}",
    )

    passed = sum(1 for v in letters.values() if v["lolos"] is True)
    evaluated = sum(1 for v in letters.values() if v["lolos"] is not None)
    out = {
        "ticker": ticker,
        "canslim_score": passed,
        "canslim_total": 7,
        "evaluated": evaluated,
        "letters": letters,
        "verdict": _verdict(passed, evaluated),
        "data_source": metrics.get("source"),
    }
    # Guardrail: jika fund punya EPS tapi C masih n/a / beda status → sync
    if fund is not None:
        notes = sync_letter_c_from_fund(out, fund)
        if notes:
            out["sync_notes"] = notes
    return out


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
