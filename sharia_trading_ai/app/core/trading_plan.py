"""
Money Management & Trading Plan (modul hal. 51-56).

  - Position sizing : LOT = Modal / Market Price / 100
  - Money Management: Trading fund 50%, Loss fund 3%, Profit fund 6%
  - Taichi Trading Plan: OB1/OB2/OB3 (Open Buy) + perhitungan average
  - RRR (Risk Reward Ratio) min 1:2

Catatan syariah: semua perhitungan TUNAI (non-margin), long-only — sesuai
Fatwa DSN-MUI No. 80/2011. Tidak ada leverage/short.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from app.config import MM


# --------------------------------------------------------------------------- #
#  Fraksi harga BEI                                                           #
# --------------------------------------------------------------------------- #
def bei_tick(price: float, is_us: bool = False) -> float:
    if is_us:
        return 0.01
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def round_to_tick(price: float, ticker: Optional[str] = None) -> float:
    from app.data.provider import is_us_ticker
    is_us = is_us_ticker(ticker) if ticker else False
    tick = bei_tick(price, is_us)
    res = round(price / tick) * tick
    return round(res, 2) if is_us else int(res)


# --------------------------------------------------------------------------- #
#  Money Management — pembagian dana (modul hal. 53)                          #
# --------------------------------------------------------------------------- #
def money_management(idle_money: float, num_stocks: int = 1,
                     risk_pct: float = MM.LOSS_FUND_PCT,
                     profit_pct: float = MM.PROFIT_FUND_PCT) -> dict[str, Any]:
    """
    Money Management (metode "MM TP Baru"):
      Idle Fund    = Modal
      Trading Fund = 50% x Idle Fund
      Bid Fund     = Trading Fund / Jumlah Saham   (= kemampuan beli tiap emiten)
      Loss Fund    = Bid Fund x Risk%              (Risk maks 5%)
      Profit Fund  = Bid Fund x Profit%            (Target min 2x Risk)
    """
    num_stocks = max(1, num_stocks)

    # aturan: Risk maks 5% ; Target profit min 2x Risk
    notes: list[str] = []
    if risk_pct > MM.RISK_MAX_PCT:
        notes.append(f"Risk dibatasi maksimal {MM.RISK_MAX_PCT}% (input {risk_pct}%).")
        risk_pct = MM.RISK_MAX_PCT
    min_profit = MM.PROFIT_MIN_RISK_MULT * risk_pct
    if profit_pct < min_profit:
        notes.append(f"Target profit dinaikkan ke {min_profit}% (min {MM.PROFIT_MIN_RISK_MULT}x risk).")
        profit_pct = min_profit

    idle_fund = idle_money
    trading_fund = idle_fund * MM.TRADING_FUND_PCT / 100
    bid_fund = trading_fund / num_stocks
    loss_fund = bid_fund * risk_pct / 100
    profit_fund = bid_fund * profit_pct / 100

    return {
        # input
        "modal": round(idle_money),
        "jumlah_saham": num_stocks,
        "risk_pct": risk_pct,
        "profit_pct": profit_pct,
        # per emiten (potensi)
        "kemampuan_beli_per_emiten": round(bid_fund),
        "potensi_risk_per_emiten": round(loss_fund),
        "potensi_profit_per_emiten": round(profit_fund),
        # Money Management Result
        "idle_fund": round(idle_fund),
        "trading_fund": round(trading_fund),
        "trading_fund_pct": MM.TRADING_FUND_PCT,
        "bid_fund": round(bid_fund),
        "loss_fund": round(loss_fund),
        "profit_fund": round(profit_fund),
        # kompat lama
        "idle_money": round(idle_money),
        "bid_fund_per_saham": round(bid_fund),
        "loss_fund_per_saham": round(loss_fund),
        "profit_fund_per_saham": round(profit_fund),
        "loss_fund_pct": risk_pct,
        "profit_fund_pct": profit_pct,
        "keterangan": {
            "idle_fund": "Uang yang menganggur tanpa digunakan untuk tujuan apa pun dalam waktu dekat.",
            "trading_fund": "Ambil setengah dari modal sebagai dana ketika kondisi trading urgent.",
            "bid_fund": "Dana untuk membeli saham di satu emiten perusahaan.",
            "loss_fund": "Dana kerugian yang siap ditanggung bila trading plan gagal.",
            "profit_fund": "Target keuntungan tiap emiten (min 2x risk).",
        },
        "aturan": notes,
        "catatan": "Hanya gunakan UANG DINGIN. Trading tunai, tanpa margin (sesuai syariah).",
    }


# --------------------------------------------------------------------------- #
#  Position sizing (modul hal. 55)                                            #
# --------------------------------------------------------------------------- #
def position_size(modal: float, market_price: float) -> dict[str, Any]:
    if market_price <= 0:
        raise ValueError("market_price harus > 0")
    lots = math.floor(modal / market_price / MM.SHARES_PER_LOT)
    shares = lots * MM.SHARES_PER_LOT
    cost = shares * market_price
    return {
        "modal": round(modal),
        "market_price": round(market_price),
        "lot": lots,
        "lembar": shares,
        "estimasi_biaya": round(cost),
        "sisa_modal": round(modal - cost),
    }


# --------------------------------------------------------------------------- #
#  Taichi Trading Plan (modul hal. 54-56)                                     #
# --------------------------------------------------------------------------- #
def taichi_plan(
    modal: float,
    market_price: float,
    mode: str = "konservatif",
    cl_price: Optional[float] = None,
    risk_pct: float = MM.LOSS_FUND_PCT,
    ticker: Optional[str] = None,
) -> dict[str, Any]:
    """
    Bagi entry jadi 3 titik (OB1/OB2/OB3).
      OB1 = Market Price, OB3 = titik Cut Loss (= MP - risk%), OB2 = (OB1+OB3)/2
      Cash/CL area = 3 fraksi di bawah OB3
    Selaras Money Management: OB3 default diturunkan dari Risk% (maks 5%).
    Hanya dipakai di area AKUMULASI / UPTREND.
    """
    from app.data.provider import is_us_ticker
    is_us = is_us_ticker(ticker) if ticker else False
    shares_per_lot = 1 if is_us else MM.SHARES_PER_LOT
    
    mode = mode.lower()
    risk_pct = min(risk_pct, MM.RISK_MAX_PCT)
    total_lot = math.floor(modal / market_price / shares_per_lot)
    if total_lot < 1:
        return {"error": f"modal tidak cukup untuk 1 {'lembar' if is_us else 'lot'} pada harga ini",
                "market_price": round(market_price, 2) if is_us else round(market_price), "modal": round(modal)}

    # alokasi lot per OB
    if mode == "moderat":
        r1, r2, r3 = MM.TAICHI_MODERAT
        lot1 = round(total_lot * r1 / 100)
        lot2 = round(total_lot * r2 / 100)
    else:
        mode = "konservatif"
        r1, r2, r3 = MM.TAICHI_KONSERVATIF
        denom = r1 + r2 + r3
        lot1 = round(total_lot * r1 / denom)
        lot2 = round(total_lot * r2 / denom)
    lot3 = total_lot - lot1 - lot2  # sisa ke OB3 (terbesar)

    # harga tiap OB
    ob1 = round_to_tick(market_price, ticker)
    ob3 = round_to_tick(cl_price, ticker) if cl_price else round_to_tick(market_price * (1 - risk_pct / 100), ticker)
    ob2 = round_to_tick((ob1 + ob3) / 2, ticker)
    cash_cl = ob3 - 3 * bei_tick(ob3, is_us)  # 3 fraksi di bawah OB3

    obs = [
        {"titik": "OB1", "harga": ob1, "lot": lot1, "nilai": round(ob1 * lot1 * shares_per_lot, 2)},
        {"titik": "OB2", "harga": ob2, "lot": lot2, "nilai": round(ob2 * lot2 * shares_per_lot, 2)},
        {"titik": "OB3", "harga": ob3, "lot": lot3, "nilai": round(ob3 * lot3 * shares_per_lot, 2)},
    ]

    # average bila semua OB terisi
    tot_lot = sum(o["lot"] for o in obs)
    tot_val = sum(o["nilai"] for o in obs)
    avg = round(tot_val / (tot_lot * shares_per_lot), 2) if tot_lot else None

    return {
        "mode": mode,
        "market_price": ob1,
        "risk_pct": risk_pct,
        "total_lot": total_lot,
        "open_buy": obs,
        "cash_cl_area": round(cash_cl, 2) if is_us else int(cash_cl),
        "average_jika_full": avg,
        "estimasi_modal_terpakai": round(tot_val, 2) if is_us else round(tot_val),
        "catatan": f"OB3 (cut loss) = harga − {risk_pct}%. Taichi hanya valid di area Akumulasi & Uptrend.",
    }


# --------------------------------------------------------------------------- #
#  RRR — Risk Reward Ratio (modul hal. 51-52)                                 #
# --------------------------------------------------------------------------- #
def risk_reward(buy: float, cut_loss: Optional[float] = None,
                take_profit: Optional[float] = None,
                risk_pct: Optional[float] = None, profit_pct: Optional[float] = None,
                target_reward_mult: int = 2, ticker: Optional[str] = None) -> dict[str, Any]:
    """
    Selaras Money Management: cut loss & take profit boleh diturunkan dari
    Risk% & Target Profit% (Risk maks 5%, Profit min 2x risk), atau diisi manual.

      Cut Loss    = harga beli x (1 - risk%)
      Take Profit = harga beli x (1 + profit%)
      RRR         = reward / risk  (min disarankan 1:2)
    """
    notes: list[str] = []
    cl_from_pct = tp_from_pct = False

    # turunkan cut_loss dari risk% bila tak diisi manual
    if cut_loss is None and risk_pct is not None:
        if risk_pct > MM.RISK_MAX_PCT:
            notes.append(f"Risk dibatasi maksimal {MM.RISK_MAX_PCT}% (input {risk_pct}%).")
            risk_pct = MM.RISK_MAX_PCT
        cut_loss = buy * (1 - risk_pct / 100)
        cl_from_pct = True
    if cut_loss is None:
        return {"error": "isi Cut Loss atau Risk %"}

    risk = buy - cut_loss
    if risk <= 0:
        return {"error": "cut loss harus di bawah harga beli (long-only)"}

    # turunkan take_profit dari profit% (atau RRR target)
    if take_profit is None:
        if profit_pct is not None:
            min_profit = MM.PROFIT_MIN_RISK_MULT * (risk_pct if cl_from_pct else round(risk / buy * 100, 2))
            if profit_pct < min_profit:
                notes.append(f"Target profit dinaikkan ke {min_profit}% (min {MM.PROFIT_MIN_RISK_MULT}x risk).")
                profit_pct = min_profit
            take_profit = buy * (1 + profit_pct / 100)
            tp_from_pct = True
        else:
            take_profit = buy + risk * target_reward_mult

    buy_r, cl_r, tp_r = round_to_tick(buy, ticker), round_to_tick(cut_loss, ticker), round_to_tick(take_profit, ticker)
    risk_r, reward_r = buy_r - cl_r, tp_r - buy_r
    # RRR: pakai persentase (bersih dari pembulatan tick) bila mode persentase
    if cl_from_pct and tp_from_pct and risk_pct:
        ratio = round(profit_pct / risk_pct, 2)
        eff_risk, eff_profit = risk_pct, profit_pct
    else:
        ratio = round(reward_r / risk_r, 2) if risk_r else None
        eff_risk = round(risk_r / buy_r * 100, 2) if buy_r else None
        eff_profit = round(reward_r / buy_r * 100, 2) if buy_r else None
    return {
        "harga_beli": buy_r,
        "cut_loss": cl_r,
        "take_profit": tp_r,
        "risk_pct": eff_risk,
        "profit_pct": eff_profit,
        "risk_per_lembar": round(risk_r, 2),
        "reward_per_lembar": round(reward_r, 2),
        "rrr": f"1 : {ratio}" if ratio else None,
        "rrr_value": ratio,
        "layak": ratio is not None and ratio >= 2,
        "aturan": notes,
        "catatan": f"RRR minimal disarankan 1:{target_reward_mult} (modul hal. 52).",
    }
