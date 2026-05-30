"""
Position Sizing — Taichi Trading Plan (Doddy Eka Putra)
=======================================================
Implementasi konsep money management dari panduan Sharia Investment Module.

KONSEP:
  Idle Money       : total uang menganggur
  Trading Fund     : 50% dari idle money (sisanya simpanan/cash buffer)
  Bid Fund         : trading fund / jumlah saham yang akan di-trade (1, 2, 3, ...)
  Loss Fund (CL)   : bid fund × 3%   ← cut-loss yang lebih ketat dari O'Neil
  Profit Fund (TP) : bid fund × 6%   ← take-profit lebih cepat
  RRR              : Reward / Risk = 6%/3% = 2:1

POSITION SIZING (LOT):
  LOT = Bid Fund / MP (market price) / 100   ← 100 lembar/lot

TAICHI ENTRY SPLIT (DCA bertahap):
  Konservatif :  Ob1 = 14% × LOT
                 Ob2 = 29% × LOT
                 Ob3 = 57% × LOT  (buy lebih banyak di harga lebih rendah)
  Moderat     :  Ob1 = 20% × LOT
                 Ob2 = 30% × LOT
                 Ob3 = 50% × LOT
  Agresif     :  Ob1 = 30% × LOT
                 Ob2 = 30% × LOT
                 Ob3 = 40% × LOT
"""

from typing import Dict, List, Optional


# Cut-loss / Take-profit Taichi (Doddy)
TAICHI_CUT_LOSS_PCT = -3.0
TAICHI_TAKE_PROFIT_PCT = 6.0
TAICHI_RRR = abs(TAICHI_TAKE_PROFIT_PCT / TAICHI_CUT_LOSS_PCT)  # 2.0


PROFILES = {
    "konservatif": [0.14, 0.29, 0.57],
    "moderat":     [0.20, 0.30, 0.50],
    "agresif":     [0.30, 0.30, 0.40],
}


def calc_position_size(
    idle_money: float,
    n_stocks: int,
    market_price: float,
    profile: str = "moderat",
    trading_fund_pct: float = 0.5
) -> Dict:
    """
    Hitung position sizing lengkap untuk 1 saham.

    Args:
        idle_money: total uang menganggur (Rp)
        n_stocks: jumlah saham yang ingin ditradingkan (1-10 disarankan)
        market_price: harga saham saat ini (Rp/lembar)
        profile: 'konservatif' | 'moderat' | 'agresif'
        trading_fund_pct: porsi idle money yang dipakai trading (default 50%)

    Returns:
        dict berisi semua angka yang trader butuhkan.
    """
    if idle_money <= 0 or n_stocks < 1 or market_price <= 0:
        return {"error": "Input tidak valid (idle_money, n_stocks, market_price harus > 0)"}

    if profile not in PROFILES:
        profile = "moderat"

    trading_fund = idle_money * trading_fund_pct
    bid_fund = trading_fund / n_stocks

    # LOT calculation: 100 lembar = 1 lot
    total_lot = int(bid_fund / market_price / 100)
    if total_lot < 1:
        return {
            "error": f"Modal terlalu kecil — bid fund Rp {bid_fund:,.0f} "
                     f"tidak cukup untuk 1 lot di harga {market_price:,.0f}"
        }

    # Taichi entry split
    splits = PROFILES[profile]
    ob1_lot = max(1, int(total_lot * splits[0]))
    ob2_lot = max(1, int(total_lot * splits[1]))
    ob3_lot = max(0, total_lot - ob1_lot - ob2_lot)  # sisa

    # Loss fund / Profit fund (rupiah)
    loss_fund = bid_fund * abs(TAICHI_CUT_LOSS_PCT) / 100
    profit_fund = bid_fund * TAICHI_TAKE_PROFIT_PCT / 100

    # Target & Stop price
    cut_loss_price = market_price * (1 + TAICHI_CUT_LOSS_PCT / 100)
    take_profit_price = market_price * (1 + TAICHI_TAKE_PROFIT_PCT / 100)

    # Recommended Ob entries (price ladder, makin turun)
    # Ob1 di harga sekarang, Ob2 -1.5%, Ob3 -3% (di area cut-loss)
    ob1_price = market_price
    ob2_price = market_price * 0.985
    ob3_price = market_price * 0.970  # batas akhir (= cut-loss area)

    return {
        "input": {
            "idle_money": idle_money,
            "n_stocks": n_stocks,
            "market_price": market_price,
            "profile": profile,
            "trading_fund_pct": trading_fund_pct,
        },
        "money": {
            "trading_fund": round(trading_fund, 0),
            "bid_fund": round(bid_fund, 0),
            "loss_fund": round(loss_fund, 0),
            "profit_fund": round(profit_fund, 0),
            "rrr": TAICHI_RRR,
        },
        "lot": {
            "total": total_lot,
            "ob1": ob1_lot,
            "ob2": ob2_lot,
            "ob3": ob3_lot,
        },
        "price": {
            "ob1": round(ob1_price, 0),
            "ob2": round(ob2_price, 0),
            "ob3": round(ob3_price, 0),
            "cut_loss": round(cut_loss_price, 0),
            "take_profit": round(take_profit_price, 0),
        },
        "rules": {
            "cut_loss_pct": TAICHI_CUT_LOSS_PCT,
            "take_profit_pct": TAICHI_TAKE_PROFIT_PCT,
        },
        "instructions": [
            f"1. Pasang limit BUY {ob1_lot} lot di harga {ob1_price:,.0f} (Ob1)",
            f"2. Kalau turun, pasang limit BUY {ob2_lot} lot di {ob2_price:,.0f} (Ob2)",
            f"3. Kalau turun lagi, pasang limit BUY {ob3_lot} lot di {ob3_price:,.0f} (Ob3)",
            f"4. STOP LOSS WAJIB di harga ≤ {cut_loss_price:,.0f} (-3%)",
            f"5. TARGET PROFIT di harga {take_profit_price:,.0f} (+6%)",
        ]
    }


def calc_average(entries: List[Dict]) -> Dict:
    """
    Hitung harga rata-rata setelah multi-entry (Taichi style).

    Args:
        entries: list of {"price": float, "lot": int}

    Returns:
        dict dengan total_lot, total_cost, average_price
    """
    if not entries:
        return {"total_lot": 0, "total_cost": 0, "average_price": 0}

    total_cost = sum(e["price"] * e["lot"] * 100 for e in entries)
    total_lot = sum(e["lot"] for e in entries)
    avg_price = total_cost / (total_lot * 100) if total_lot else 0

    return {
        "total_lot": total_lot,
        "total_lembar": total_lot * 100,
        "total_cost": round(total_cost, 0),
        "average_price": round(avg_price, 2),
        "entries": entries,
    }


if __name__ == "__main__":
    # Smoke test (contoh dari PDF):
    # Modal = 5.000.000, MP = 4200, n_stocks = 1 → LOT = 11
    result = calc_position_size(
        idle_money=10_000_000,  # Trading fund 50% = 5jt
        n_stocks=1,
        market_price=4200,
        profile="moderat"
    )
    print("=== TEST POSITION SIZING (Taichi) ===")
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print()
    print("=== TEST AVERAGE CALCULATION ===")
    avg = calc_average([
        {"price": 4200, "lot": 1},
        {"price": 4130, "lot": 2},
    ])
    print(json.dumps(avg, indent=2, ensure_ascii=False))
