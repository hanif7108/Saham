"""
Backtest Engine
===============
Simulasi strategi trading sederhana berbasis sinyal teknikal +
exit rule (cut loss / take profit).

Strategi default:
  - Entry  : signal == "BUY" (dari technical_analysis.compute_signals
             dihitung pada window rolling)
  - Exit   : SELL kalau:
             * harga turun <= -7% dari entry (cut loss)
             * harga naik  >= +20% dari entry (take profit)
             * signal turun ke "SELL"
  - Posisi : maksimum 1 posisi per ticker, no leverage.
  - Modal awal: Rp 10.000.000 (asumsi).

Output:
  - DataFrame trades (entry_date, exit_date, entry_price, exit_price, pnl_pct, holding_days)
  - Metrics: total return, win rate, max drawdown, n trades, avg holding
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .technical_analysis import compute_signals


# ----------------------------- ENTRY/EXIT RULES ----------------------------- #

DEFAULT_CONFIG = {
    "cut_loss_pct": -3.0,       # Taichi rule (Doddy): tutup posisi kalau loss <= -3%
    "take_profit_pct": 6.0,     # Taichi rule (Doddy): tutup posisi kalau profit >= +6%
    "min_lookback": 60,         # butuh minimal 60 hari sebelum bisa hitung sinyal
    "rolling_window": 60,       # window untuk hitung sinyal di setiap titik waktu
}


def _signal_at(prices_df: pd.DataFrame, idx: int, window: int) -> str:
    """Hitung sinyal pada index ke-idx dengan rolling window."""
    start = max(0, idx - window + 1)
    sub = prices_df.iloc[start:idx + 1]
    res = compute_signals(sub)
    return res.get("signal", "HOLD")


# ----------------------------- BACKTEST ----------------------------- #

def backtest_ticker(
    prices_df: pd.DataFrame,
    config: Optional[Dict] = None
) -> Dict:
    """
    Jalankan backtest pada satu ticker.

    Args:
        prices_df: DataFrame harga harian dengan index DatetimeIndex
                   dan kolom 'Close' + 'Volume'.
        config: dict konfigurasi (lihat DEFAULT_CONFIG).

    Returns:
        dict dengan key:
          - trades: list[dict]
          - metrics: dict (total_return_pct, win_rate, n_trades, max_dd, avg_holding)
          - equity_curve: list (untuk plot)
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if prices_df is None or prices_df.empty or "Close" not in prices_df.columns:
        return {"trades": [], "metrics": {}, "equity_curve": []}

    prices_df = prices_df.copy().sort_index()
    n = len(prices_df)

    if n < cfg["min_lookback"] + 5:
        return {"trades": [], "metrics": {"note": "Data tidak cukup"}, "equity_curve": []}

    in_position = False
    entry_price = 0.0
    entry_idx = None
    trades: List[Dict] = []

    capital = 1.0  # equity unit, mulai 1.0 (= 100%)
    equity_curve = []

    for i in range(cfg["min_lookback"], n):
        date = prices_df.index[i]
        price = float(prices_df["Close"].iloc[i])

        if not in_position:
            # Cek sinyal entry
            sig = _signal_at(prices_df, i, cfg["rolling_window"])
            if sig == "BUY":
                in_position = True
                entry_price = price
                entry_idx = i
        else:
            pnl_pct = (price - entry_price) / entry_price * 100
            should_exit = False
            exit_reason = ""

            if pnl_pct <= cfg["cut_loss_pct"]:
                should_exit = True
                exit_reason = "CUT LOSS"
            elif pnl_pct >= cfg["take_profit_pct"]:
                should_exit = True
                exit_reason = "TAKE PROFIT"
            else:
                sig = _signal_at(prices_df, i, cfg["rolling_window"])
                if sig == "SELL":
                    should_exit = True
                    exit_reason = "TECH SELL"

            if should_exit:
                holding = i - entry_idx
                trades.append({
                    "entry_date": str(prices_df.index[entry_idx].date()),
                    "exit_date": str(date.date()) if hasattr(date, "date") else str(date),
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(price, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "holding_days": int(holding),
                    "reason": exit_reason
                })
                # Update equity (compounding 1 unit posisi)
                capital *= (1 + pnl_pct / 100)
                in_position = False
                entry_price = 0.0
                entry_idx = None

        equity_curve.append({
            "date": str(date.date()) if hasattr(date, "date") else str(date),
            "equity": round(capital, 4)
        })

    # Close any open position at last price
    if in_position and entry_idx is not None:
        last_price = float(prices_df["Close"].iloc[-1])
        pnl_pct = (last_price - entry_price) / entry_price * 100
        trades.append({
            "entry_date": str(prices_df.index[entry_idx].date()),
            "exit_date": str(prices_df.index[-1].date()),
            "entry_price": round(entry_price, 2),
            "exit_price": round(last_price, 2),
            "pnl_pct": round(pnl_pct, 2),
            "holding_days": int(n - 1 - entry_idx),
            "reason": "EOD CLOSE"
        })
        capital *= (1 + pnl_pct / 100)

    # Metrics
    if not trades:
        metrics = {
            "total_return_pct": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "max_dd_pct": 0.0,
            "avg_holding": 0,
        }
    else:
        pnls = [t["pnl_pct"] for t in trades]
        wins = [p for p in pnls if p > 0]

        # Max drawdown dari equity curve
        eq_values = [e["equity"] for e in equity_curve]
        running_max = np.maximum.accumulate(eq_values) if eq_values else [1.0]
        drawdowns = (np.array(eq_values) - running_max) / running_max * 100 if eq_values else [0]
        max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

        metrics = {
            "total_return_pct": round((capital - 1.0) * 100, 2),
            "n_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "max_dd_pct": round(max_dd, 2),
            "avg_holding": round(float(np.mean([t["holding_days"] for t in trades])), 1),
            "best_trade": round(max(pnls), 2),
            "worst_trade": round(min(pnls), 2),
        }

    return {
        "trades": trades,
        "metrics": metrics,
        "equity_curve": equity_curve
    }


def backtest_portfolio(
    tickers: List[str],
    cache_obj,
    period: str = "1y",
    config: Optional[Dict] = None
) -> Dict:
    """
    Backtest banyak ticker (rata-rata bobot equal).

    Args:
        tickers: list ticker (tanpa .JK)
        cache_obj: instance Cache untuk fetch history
        period: yfinance period string
        config: konfigurasi backtest

    Returns:
        dict ringkasan + per-ticker results.
    """
    per_ticker = {}
    all_trades = []
    final_returns = []

    for tk in tickers:
        df = cache_obj.get_history(tk, period=period, ttl_minutes=24 * 60)
        if df is None or df.empty:
            per_ticker[tk] = {"error": "no data"}
            continue
        result = backtest_ticker(df, config)
        per_ticker[tk] = result["metrics"]
        all_trades.extend([{**t, "ticker": tk} for t in result["trades"]])
        if result["metrics"].get("n_trades", 0) > 0:
            final_returns.append(result["metrics"]["total_return_pct"])

    summary = {
        "tickers_evaluated": len(tickers),
        "tickers_with_trades": len(final_returns),
        "avg_return_pct": round(float(np.mean(final_returns)), 2) if final_returns else 0.0,
        "best_ticker": max(per_ticker.items(),
                           key=lambda kv: kv[1].get("total_return_pct", -1e9))[0] if per_ticker else None,
        "total_trades": len(all_trades),
    }

    return {
        "summary": summary,
        "per_ticker": per_ticker,
        "all_trades": all_trades
    }


if __name__ == "__main__":
    # Smoke test pakai data dummy
    np.random.seed(7)
    n = 250
    prices = 1000 + np.cumsum(np.random.randn(n) * 15)
    df = pd.DataFrame({
        "Close": prices,
        "Volume": np.random.randint(500_000, 5_000_000, n)
    }, index=pd.date_range("2024-01-01", periods=n))

    res = backtest_ticker(df)
    print("=== SMOKE TEST backtest.py ===")
    print("Metrics:", res["metrics"])
    print(f"N trades: {len(res['trades'])}")
    if res["trades"]:
        print("Sample trade:", res["trades"][0])
