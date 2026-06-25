"""
Asset Aggregator — Single Source of Truth untuk Total Aset
==========================================================
SATU module yang dipanggil oleh /api/dashboard, /api/broker_portfolio,
dan /api/portfolio supaya semua tab menampilkan angka yang IDENTIK.

Sumber data (berurutan prioritas):
  1. broker_transactions.csv — audit trail Bibit/Pluang/Profit Anywhere
     → master source untuk Bibit holdings + saldo kas
  2. portfolio.csv — manual quick-input
     → fallback untuk ticker yang TIDAK ADA di broker_transactions
     → otomatis di-sync dari broker_transactions untuk ticker yang
       sudah ada di sana (jadi tidak ada double-count)
  3. pegadaian_transactions.csv — emas digital
     → di-treat sebagai platform tambahan

Single output dict:
  {
    "total_asset_rp": float,
    "breakdown": {
        "stocks_rp": ...,   # nilai semua holdings saham (current price)
        "cash_rp": ...,     # cash semua broker + Pegadaian saldo
        "gold_rp": ...,     # nilai emas Pegadaian (current price)
    },
    "platforms": {
        "Bibit": {cash, stock_value, total_value, holdings: [...]},
        "Pluang": {...},
        "Pegadaian": {gold_value, gram, cash, total_value, ...},
        "Manual (portfolio.csv)": {stock_value, holdings: [...]}
    },
    "holdings": [...],       # gabungan semua holdings dengan platform tag
    "warnings": [...]        # konflik / inconsistency
  }
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Callable, Any

import pandas as pd


def aggregate_all_assets(
    broker_tx_path: str,
    portfolio_csv_path: str,
    pegadaian_tx_path: str,
    get_current_price: Callable[[str], float],
    get_gold_price_per_gram: Callable[[], float],
) -> Dict[str, Any]:
    """
    Gabungkan semua sumber aset jadi satu output canonical.

    Args:
        broker_tx_path: path ke broker_transactions.csv
        portfolio_csv_path: path ke portfolio.csv
        pegadaian_tx_path: path ke pegadaian_transactions.csv
        get_current_price: callable(ticker) → harga current per lembar (Rp)
        get_gold_price_per_gram: callable() → harga emas Pegadaian per gram

    Returns:
        dict canonical (lihat docstring di header file).
    """
    warnings: List[str] = []

    # ---------- 1. Broker transactions: hitung holdings + cash per platform ----------
    broker_holdings: Dict[str, Dict[str, Dict]] = {}  # platform → ticker → {shares, total_cost, avg_price}
    broker_cash: Dict[str, float] = {}
    broker_topup: Dict[str, float] = {}
    broker_realized_pnl: Dict[str, float] = {}

    if os.path.exists(broker_tx_path):
        try:
            df = pd.read_csv(broker_tx_path)
            if not df.empty:
                df["tanggal"] = pd.to_datetime(df["tanggal"])
                df = df.sort_values("tanggal").reset_index(drop=True)
                for _, row in df.iterrows():
                    plat = str(row.get("platform") or "Bibit")
                    tipe = str(row.get("tipe") or "").upper()
                    ticker = str(row.get("ticker") or "").upper().strip() if pd.notna(row.get("ticker")) else ""
                    harga = float(row.get("harga") or 0)
                    jumlah = float(row.get("jumlah") or 0)
                    nominal = float(row.get("nominal") or 0)
                    bfee = float(row.get("broker_fee") or 0) if pd.notna(row.get("broker_fee")) else 0
                    efee = float(row.get("exchange_fee") or 0) if pd.notna(row.get("exchange_fee")) else 0

                    broker_cash.setdefault(plat, 0.0)
                    broker_topup.setdefault(plat, 0.0)
                    broker_realized_pnl.setdefault(plat, 0.0)
                    broker_holdings.setdefault(plat, {})

                    if tipe == "TOPUP":
                        broker_cash[plat] += nominal
                        broker_topup[plat] += nominal
                    elif tipe == "WITHDRAWAL":
                        broker_cash[plat] -= nominal
                        broker_topup[plat] -= nominal
                    elif tipe == "BUY":
                        cost = (harga * jumlah) + bfee + efee
                        broker_cash[plat] -= cost
                        h = broker_holdings[plat].setdefault(ticker, {"shares": 0.0, "total_cost": 0.0, "avg_price": 0.0})
                        h["shares"] += jumlah
                        h["total_cost"] += cost
                        h["avg_price"] = h["total_cost"] / h["shares"] if h["shares"] > 0 else 0
                    elif tipe == "SELL":
                        h = broker_holdings[plat].get(ticker)
                        if not h or h["shares"] <= 0:
                            # Tidak punya saham — skip & warn
                            warnings.append(
                                f"⚠ SELL {ticker} {jumlah:.0f} lbr ditolak: "
                                f"tidak ada holding di {plat}. Tx ID {row.get('id')}."
                            )
                            continue
                        # Cap jumlah jual ke shares yang dimiliki
                        actual_sold = min(jumlah, h["shares"])
                        if actual_sold < jumlah:
                            warnings.append(
                                f"⚠ SELL {ticker} {jumlah:.0f} lbr di-cap jadi {actual_sold:.0f} "
                                f"(holding hanya {h['shares']:.0f} lbr di {plat}). Tx ID {row.get('id')}."
                            )
                        rev = (harga * actual_sold) - bfee - efee
                        broker_cash[plat] += rev
                        avg = h["avg_price"]
                        cost_basis = avg * actual_sold
                        realized = rev - cost_basis
                        broker_realized_pnl[plat] += realized
                        h["shares"] -= actual_sold
                        h["total_cost"] -= cost_basis
                        if h["shares"] <= 0:
                            del broker_holdings[plat][ticker]
        except Exception as e:
            warnings.append(f"Error parsing {broker_tx_path}: {e}")

    # ---------- 2. portfolio.csv: hanya untuk ticker yang TIDAK ada di broker_holdings ----------
    # Auto-sync: jika ticker portfolio.csv ada di broker, prefer broker (overwrite)
    manual_only: List[Dict] = []   # holdings dari portfolio.csv yang tidak overlap dengan broker
    sync_actions: List[str] = []
    broker_tickers_set = set()
    for plat, hmap in broker_holdings.items():
        for tk, hd in hmap.items():
            if hd["shares"] > 0:
                broker_tickers_set.add(tk)

    if os.path.exists(portfolio_csv_path):
        try:
            pf = pd.read_csv(portfolio_csv_path)
            for _, row in pf.iterrows():
                tk = str(row.get("Ticker") or "").upper().strip()
                if not tk:
                    continue
                lot = float(row.get("Jumlah Lot") or 0)
                avg = float(row.get("Harga Beli") or 0)
                shares = lot * 100
                if tk in broker_tickers_set:
                    # Cek apakah lot manual sama dengan broker — kalau beda, peringatkan
                    broker_shares = 0.0
                    for plat, hmap in broker_holdings.items():
                        if tk in hmap:
                            broker_shares += hmap[tk]["shares"]
                    if abs(broker_shares - shares) > 0.5:  # toleransi rounding
                        warnings.append(
                            f"⚠ {tk}: portfolio.csv = {lot:.0f} lot, broker_transactions = {broker_shares/100:.0f} lot. "
                            f"Pakai broker_transactions (audit trail) sebagai master. "
                            f"portfolio.csv akan di-sync."
                        )
                    sync_actions.append(tk)
                else:
                    # Ticker hanya ada di portfolio.csv — keep
                    manual_only.append({"ticker": tk, "lot": lot, "avg_price": avg, "shares": shares})
        except Exception as e:
            warnings.append(f"Error parsing {portfolio_csv_path}: {e}")

    # ---------- 3. Auto-sync portfolio.csv DARI broker_transactions ----------
    # Tulis ulang portfolio.csv supaya match: broker holdings + manual_only entries
    try:
        sync_rows = []
        for plat, hmap in broker_holdings.items():
            for tk, hd in hmap.items():
                if hd["shares"] > 0:
                    sync_rows.append({
                        "Ticker": tk,
                        "Harga Beli": round(hd["avg_price"], 2),
                        "Jumlah Lot": int(hd["shares"] / 100),
                    })
        for m in manual_only:
            sync_rows.append({
                "Ticker": m["ticker"],
                "Harga Beli": round(m["avg_price"], 2),
                "Jumlah Lot": int(m["lot"]),
            })
        if sync_rows:
            pd.DataFrame(sync_rows).to_csv(portfolio_csv_path, index=False)
    except Exception as e:
        warnings.append(f"Error sync portfolio.csv: {e}")

    # ---------- 4. Hitung nilai current per holding ----------
    all_holdings: List[Dict] = []   # gabungan, dengan platform tag
    stocks_value_rp = 0.0
    unrealized_pnl_rp = 0.0
    platform_stock_values: Dict[str, float] = {}
    platform_unrealized_pnl: Dict[str, float] = {}

    for plat, hmap in broker_holdings.items():
        for tk, hd in hmap.items():
            if hd["shares"] <= 0:
                continue
            cur_price = float(get_current_price(tk) or 0)
            if cur_price <= 0:
                cur_price = hd["avg_price"]  # fallback
            cur_val = hd["shares"] * cur_price
            cost = hd["avg_price"] * hd["shares"]
            pnl_rp = cur_val - cost
            pnl_pct = (pnl_rp / cost * 100) if cost > 0 else 0

            all_holdings.append({
                "platform": plat,
                "ticker": tk,
                "shares": hd["shares"],
                "lot": hd["shares"] / 100,
                "avg_price": round(hd["avg_price"], 2),
                "current_price": round(cur_price, 2),
                "current_value": round(cur_val, 2),
                "pnl_rp": round(pnl_rp, 2),
                "pnl_pct": round(pnl_pct, 2),
                "source": "broker_transactions"
            })
            stocks_value_rp += cur_val
            unrealized_pnl_rp += pnl_rp
            platform_stock_values[plat] = platform_stock_values.get(plat, 0) + cur_val
            platform_unrealized_pnl[plat] = platform_unrealized_pnl.get(plat, 0) + pnl_rp

    # Manual-only holdings (ticker yang hanya ada di portfolio.csv)
    for m in manual_only:
        tk = m["ticker"]
        cur_price = float(get_current_price(tk) or 0)
        if cur_price <= 0:
            cur_price = m["avg_price"]
        cur_val = m["shares"] * cur_price
        cost = m["avg_price"] * m["shares"]
        pnl_rp = cur_val - cost
        pnl_pct = (pnl_rp / cost * 100) if cost > 0 else 0

        all_holdings.append({
            "platform": "Manual (portfolio.csv)",
            "ticker": tk,
            "shares": m["shares"],
            "lot": m["lot"],
            "avg_price": round(m["avg_price"], 2),
            "current_price": round(cur_price, 2),
            "current_value": round(cur_val, 2),
            "pnl_rp": round(pnl_rp, 2),
            "pnl_pct": round(pnl_pct, 2),
            "source": "portfolio.csv"
        })
        stocks_value_rp += cur_val
        unrealized_pnl_rp += pnl_rp
        plat = "Manual (portfolio.csv)"
        platform_stock_values[plat] = platform_stock_values.get(plat, 0) + cur_val
        platform_unrealized_pnl[plat] = platform_unrealized_pnl.get(plat, 0) + pnl_rp

    # ---------- 5. Cash semua broker ----------
    # Adjust negatif min cash → implied deposit (existing logic)
    broker_cash_total = sum(broker_cash.values())

    # ---------- 6. Pegadaian (emas digital) ----------
    pegadaian_summary = {"total_gram": 0, "current_value_rp": 0, "saldo_rp": 0,
                         "avg_buy_price": 0, "pnl_rp": 0, "pnl_pct": 0, "n_tx": 0}
    try:
        from modules import pegadaian as pgd
        gold_price = float(get_gold_price_per_gram() or 0)
        pegadaian_summary = pgd.summarize(pegadaian_tx_path,
                                          current_price_per_gram=gold_price)
    except Exception as e:
        warnings.append(f"Pegadaian aggregation failed: {e}")

    pegadaian_gold_rp = float(pegadaian_summary.get("current_value_rp") or 0)
    pegadaian_cash_rp = max(0.0, float(pegadaian_summary.get("saldo_rp") or 0))

    # ---------- 7. Total Aset ----------
    total_asset_rp = stocks_value_rp + broker_cash_total + pegadaian_gold_rp + pegadaian_cash_rp

    # ---------- 8. Build platforms dict (mirror /api/broker_portfolio structure) ----------
    platforms = {}
    for plat in set(list(broker_cash.keys()) + list(platform_stock_values.keys())):
        c = broker_cash.get(plat, 0.0)
        sv = platform_stock_values.get(plat, 0.0)
        tv = c + sv
        tu = broker_topup.get(plat, 0.0)
        rp = broker_realized_pnl.get(plat, 0.0)
        up = platform_unrealized_pnl.get(plat, 0.0)
        platforms[plat] = {
            "cash": round(c, 2),
            "stock_value": round(sv, 2),
            "total_value": round(tv, 2),
            "total_invested": round(tu, 2),
            "realized_pnl_rp": round(rp, 2),
            "unrealized_pnl_rp": round(up, 2),
            "pnl_rp": round(rp + up, 2),
            "pnl_pct": round((rp + up) / tu * 100 if tu > 0 else 0, 2),
        }
    # Manual platform (kalau ada)
    if "Manual (portfolio.csv)" in platform_stock_values:
        plat = "Manual (portfolio.csv)"
        sv = platform_stock_values[plat]
        up = platform_unrealized_pnl[plat]
        platforms[plat] = {
            "cash": 0.0,
            "stock_value": round(sv, 2),
            "total_value": round(sv, 2),
            "total_invested": round(sv - up, 2),
            "realized_pnl_rp": 0.0,
            "unrealized_pnl_rp": round(up, 2),
            "pnl_rp": round(up, 2),
            "pnl_pct": round(up / (sv - up) * 100 if (sv - up) > 0 else 0, 2),
        }
    # Pegadaian as platform
    platforms["Pegadaian"] = {
        "cash": round(pegadaian_cash_rp, 2),
        "stock_value": 0.0,
        "gold_value": round(pegadaian_gold_rp, 2),
        "gold_gram": pegadaian_summary.get("total_gram", 0),
        "total_value": round(pegadaian_gold_rp + pegadaian_cash_rp, 2),
        "total_invested": round(pegadaian_summary.get("total_invested_rp", 0), 2),
        "avg_buy_price_per_gram": pegadaian_summary.get("avg_buy_price", 0),
        "realized_pnl_rp": 0.0,
        "unrealized_pnl_rp": round(pegadaian_summary.get("pnl_rp", 0), 2),
        "pnl_rp": round(pegadaian_summary.get("pnl_rp", 0), 2),
        "pnl_pct": pegadaian_summary.get("pnl_pct", 0),
    }

    total_invested = sum(p["total_invested"] for p in platforms.values())
    total_realized = sum(p.get("realized_pnl_rp", 0) for p in platforms.values())
    total_unrealized = sum(p.get("unrealized_pnl_rp", 0) for p in platforms.values())
    total_pnl = total_realized + total_unrealized

    return {
        "total_asset_rp": round(total_asset_rp, 0),
        "total_invested_rp": round(total_invested, 0),
        "total_pnl_rp": round(total_pnl, 0),
        "total_realized_pnl_rp": round(total_realized, 0),
        "total_unrealized_pnl_rp": round(total_unrealized, 0),
        "total_pnl_pct": round(total_pnl / total_invested * 100 if total_invested > 0 else 0, 2),
        "breakdown": {
            "stocks_rp": round(stocks_value_rp, 0),
            "cash_rp": round(broker_cash_total + pegadaian_cash_rp, 0),
            "gold_rp": round(pegadaian_gold_rp, 0),
        },
        "platforms": platforms,
        "holdings": all_holdings,
        "sync_actions": sync_actions,  # ticker yang di-sync dari broker_transactions
        "warnings": warnings,
    }
