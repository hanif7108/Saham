"""
Aturan exit posisi — trailing stop, time-stop/rotasi, dan sintesis saran.

Melengkapi decide_for_portfolio (cut-loss/take-profit statis) dengan:
  - TRAILING : profit yang sudah terkunci tidak boleh menguap
              (arm di +exit_trail_arm_pct, trigger saat turun
              trailing_stop_pct dari puncak sejak beli).
  - TIME-STOP: posisi menganggur >= exit_time_stop_days hari bursa tanpa
              mencapai target DAN sinyal ML melemah -> rotasi modal ke
              kandidat teratas. Inilah mesin "velocity bulanan" yang sehat —
              modal terus bekerja, bukan janji return.

Murni fungsi (mudah di-test); pemanggil menyuplai data harga/ML.
Semua keputusan tetap advisory — eksekusi di tangan pengguna.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.config import settings

SL_PCT = -7.0                      # selaras CUT_LOSS_PCT aplikasi


def _cfg(name: str, default: float) -> float:
    return float(getattr(settings, name, default) or default)


def days_held_bursa(added_at: Optional[str], today: Optional[date] = None) -> Optional[int]:
    """Perkiraan hari bursa sejak beli (Sen-Jum; libur BEI diabaikan)."""
    if not added_at:
        return None
    try:
        start = pd.Timestamp(str(added_at)[:10]).date()
        end = today or date.today()
        return int(np.busday_count(start, end))
    except Exception:
        return None


def peak_since(hist_close: Optional[pd.Series], added_at: Optional[str],
               fallback_days: int = 90) -> Optional[float]:
    """Puncak harga penutupan sejak tanggal beli (fallback: N hari terakhir)."""
    if hist_close is None or len(hist_close) == 0:
        return None
    s = hist_close.dropna()
    if s.empty:
        return None
    try:
        idx = pd.to_datetime(s.index)
        try:
            idx = idx.tz_localize(None)
        except TypeError:
            pass
        s.index = idx.normalize()
        if added_at:
            s = s[s.index >= pd.Timestamp(str(added_at)[:10])]
        else:
            s = s.tail(fallback_days)
        return float(s.max()) if len(s) else None
    except Exception:
        return None


def evaluate_exit(*, pnl_pct: Optional[float], price: Optional[float],
                  peak_price: Optional[float], avg_price: Optional[float],
                  days_held: Optional[int], ml: Optional[dict[str, Any]] = None,
                  tp_pct: Optional[float] = None) -> dict[str, Any]:
    """Sintesis saran exit satu posisi. Return {action, kode, alasan}.

    action: SELL | TRAIL | WASPADA | HOLD (advisory).
    Prioritas: SL -> TP -> TRAILING -> TIME-STOP -> peringatan ML -> HOLD.
    """
    tp = float(tp_pct if tp_pct is not None else _cfg("exit_tp_pct", 10.0))
    trail_arm = _cfg("exit_trail_arm_pct", 5.0)
    trail_drop = _cfg("trailing_stop_pct", 3.0)
    time_days = int(_cfg("exit_time_stop_days", 20))
    ml = ml or {}
    p_sell = float(ml.get("p_sell") or 0)
    p_buy = float(ml.get("p_buy") or 0)
    ml_ok = bool(ml.get("available"))

    if pnl_pct is not None and pnl_pct <= SL_PCT:
        return {"action": "SELL", "kode": "CUT_LOSS",
                "alasan": f"P/L {pnl_pct:+.1f}% ≤ {SL_PCT:.0f}% — batasi kerugian hari ini"}

    if pnl_pct is not None and pnl_pct >= tp:
        return {"action": "SELL", "kode": "TAKE_PROFIT",
                "alasan": f"P/L {pnl_pct:+.1f}% ≥ target +{tp:.0f}% — realisasikan"}

    # Trailing: puncak sejak beli sudah untung >= arm, lalu turun >= drop dari puncak
    if (price and peak_price and avg_price and peak_price > 0 and avg_price > 0):
        peak_gain = (peak_price / avg_price - 1) * 100
        drop = (price / peak_price - 1) * 100
        if peak_gain >= trail_arm and drop <= -trail_drop:
            return {"action": "SELL", "kode": "TRAILING",
                    "alasan": (f"pernah +{peak_gain:.1f}%, kini turun {drop:.1f}% "
                               f"dari puncak — kunci sisa profit")}
        if peak_gain >= trail_arm:
            lock = peak_price * (1 - trail_drop / 100)
            return {"action": "TRAIL", "kode": "TRAIL_ARMED",
                    "alasan": (f"profit puncak +{peak_gain:.1f}% — pasang stop di "
                               f"~{lock:,.0f} (−{trail_drop:.0f}% dari puncak)")}

    # Time-stop / rotasi: menganggur lama + ML tidak lagi mendukung
    if (days_held is not None and days_held >= time_days
            and (pnl_pct is None or pnl_pct < tp)
            and ml_ok and (p_buy < 0.40 or ml.get("signal") == "SELL")):
        return {"action": "SELL", "kode": "TIME_STOP",
                "alasan": (f"{days_held} hari bursa tanpa capai target, P(BUY) ML "
                           f"tinggal {p_buy:.0%} — rotasi ke kandidat teratas")}

    if ml_ok and p_sell >= 0.45:
        return {"action": "WASPADA", "kode": "ML_SELL_WARN",
                "alasan": f"P(SELL) ML {p_sell:.0%} — perketat stop, siap exit"}

    return {"action": "HOLD", "kode": "HOLD",
            "alasan": (f"dalam rencana (P/L {pnl_pct:+.1f}%)" if pnl_pct is not None
                       else "dalam rencana")}
