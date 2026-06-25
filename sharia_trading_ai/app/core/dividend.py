"""
Faktor DIVIDEN sebagai pendorong keputusan trading.

Data via yfinance (riwayat pembayaran, yield, ex-date, rate) — setara dengan
halaman TradingView financials-dividends, namun programatik &amp; andal. Bisa
dilengkapi kalender manual (data/dividend_calendar.json) untuk cum-date/RUPS yang
sudah diumumkan (paling presisi untuk aksi korporasi mendatang).

Dua kegunaan:
  1) Saham RUTIN dividen → faktor POSITIF (bonus skor keyakinan).
  2) Bila ex-date/RUPS DEKAT → tunda rekomendasi SELL demi menangkap dividen —
     DENGAN SYARAT bukan cut-loss dalam (agar HOLD tak menimbulkan kerugian lebih
     besar dari harapan dividen).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Optional

import httpx

from app.config import DATA_DIR
from app.data import master_data, provider

CAL = DATA_DIR / "dividend_calendar.json"

DEFER_WINDOW_DAYS = 21        # tunda SELL bila ex-date dalam ≤ N hari
MIN_EVENT_YIELD_PCT = 1.5     # dividen mendatang minimal berharga (÷ harga) agar layak ditahan


# --------------------------- kalender manual --------------------------- #
def _load_cal() -> dict[str, Any]:
    try:
        return json.loads(CAL.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_cal(data: dict) -> None:
    CAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_event(ticker: str, ex_date: str, amount: float, rups_date: Optional[str] = None) -> dict:
    date.fromisoformat(ex_date)                      # validasi
    data = _load_cal()
    data[ticker.upper()] = {"ex_date": ex_date, "amount": float(amount), "rups_date": rups_date}
    _save_cal(data)
    return data[ticker.upper()]


def remove_event(ticker: str) -> bool:
    data = _load_cal()
    if ticker.upper() in data:
        del data[ticker.upper()]
        _save_cal(data)
        return True
    return False


# --------------------------- data yfinance (cache) --------------------------- #
@lru_cache(maxsize=256)
def _stockevents(ticker: str) -> dict[str, Any]:
    """Grab data dividen publik dari stockevents.app (forward dividend + payStreak).
    Sumber ini mengagregasi pengumuman resmi; sering lebih awal dari yfinance."""
    out: dict[str, Any] = {}
    url = f"https://stockevents.app/en/stock/{provider.to_yahoo(ticker)}/dividends"
    try:
        t = httpx.get(url, timeout=12, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Macintosh)"}).text
        for key in ("nextDividend", "lastDividend"):
            m = re.search(r'"' + key + r'":(\{[^{}]*\})', t)
            if m:
                try:
                    out[key] = json.loads(m.group(1))
                except Exception:  # noqa: BLE001
                    pass
        ps = re.search(r'"payStreak":(\d+)', t)
        out["pay_streak"] = int(ps.group(1)) if ps else None
        fr = None
        for k in ("lastDividend", "nextDividend"):
            if out.get(k) and out[k].get("frequency"):
                fr = out[k]["frequency"]
                break
        if not fr:
            mf = re.search(r'"frequency":"(annual|quarterly|semi-?annual|monthly)"', t, re.I)
            fr = mf.group(1) if mf else None
        out["frequency"] = fr
    except Exception:  # noqa: BLE001
        pass
    return out


def refresh(ticker: str) -> None:
    """Kosongkan cache 1 saham agar ambil data terbaru dari web."""
    _stockevents.cache_clear()
    _yf.cache_clear()


@lru_cache(maxsize=256)
def _yf(ticker: str) -> dict[str, Any]:
    import yfinance as yf
    out: dict[str, Any] = {"history": [], "ex_unix": None, "last_amount": None,
                           "rate": None, "yield": None}
    try:
        t = yf.Ticker(provider.to_yahoo(ticker))
        div = t.dividends
        if div is not None and len(div):
            out["history"] = [(d.date(), float(v)) for d, v in div.items()]
        info = t.info or {}
        out["ex_unix"] = info.get("exDividendDate")
        out["last_amount"] = info.get("lastDividendValue")
        out["rate"] = info.get("dividendRate")
        out["yield"] = info.get("dividendYield")
    except Exception:  # noqa: BLE001
        pass
    return out


# --------------------------- profil dividen --------------------------- #
def profile(ticker: str, price: Optional[float] = None) -> dict[str, Any]:
    tk = ticker.upper()
    yf = _yf(tk)
    se = _stockevents(tk)
    hist = yf["history"]
    m = master_data.metrics(tk) or {}
    dy = m.get("dividend_yield")                     # dari master (terkurasi), tanpa network
    if price is None:
        price = m.get("market_price")

    today = date.today()
    recent = [(d, v) for d, v in hist if (today.year - d.year) <= 5]
    years_paid = len({d.year for d, _ in recent})
    pay_months = [d.month for d, _ in recent]
    streak = se.get("pay_streak")
    regular = years_paid >= 3 or (streak is not None and streak >= 3)
    last = hist[-1] if hist else None
    last_amount = (last[1] if last else None) or yf.get("last_amount") or yf.get("rate")

    # --- dividen MENDATANG: manual > stockevents(web) > yfinance future > estimasi pola ---
    up_date = up_amount = up_source = None
    cal = _load_cal().get(tk)

    def _iso(s):
        return str(s)[:10] if s else None

    if cal:
        up_date, up_amount, up_source = cal.get("ex_date"), cal.get("amount"), "kalender manual"
    elif se.get("nextDividend") and se["nextDividend"].get("exDate"):
        nd = se["nextDividend"]
        exd = _iso(nd.get("exDate"))
        if exd and exd >= today.isoformat():
            up_date, up_amount = exd, nd.get("amount")
            up_source = "stockevents.app (perkiraan)" if nd.get("isEstimated") else "stockevents.app (resmi)"
    if up_date is None and yf.get("ex_unix"):
        try:
            exd = datetime.utcfromtimestamp(int(yf["ex_unix"])).date()
            if exd >= today:
                up_date, up_amount, up_source = exd.isoformat(), last_amount, "yfinance"
        except Exception:  # noqa: BLE001
            pass
    if up_date is None and regular and pay_months:
        # estimasi: bila biasanya bayar bulan M & tahun ini belum bayar & mendekati M
        mode_month = max(set(pay_months), key=pay_months.count)
        paid_this_year = any(d.year == today.year for d, _ in recent)
        if not paid_this_year and 0 <= (mode_month - today.month) <= 2:
            est = date(today.year, mode_month, min(28, (last[0].day if last else 15)))
            up_date, up_amount, up_source = est.isoformat(), last_amount, "estimasi pola tahunan"

    days_until = None
    if up_date:
        days_until = (date.fromisoformat(up_date) - today).days
    event_yield = round(up_amount / price * 100, 2) if (up_amount and price) else None

    return {
        "ticker": tk, "regular": regular, "years_paid": years_paid,
        "pay_streak": streak, "frequency": se.get("frequency"),
        "n_payments": len(hist), "dividend_yield": dy if dy is not None else yf.get("yield"),
        "last_ex": last[0].isoformat() if last else None, "last_amount": last_amount,
        "upcoming": {
            "expected": bool(up_date), "ex_date": up_date, "amount": up_amount,
            "days_until": days_until, "event_yield_pct": event_yield, "source": up_source,
        },
    }


def dividend_bonus(ticker: str) -> float:
    """Bonus skor keyakinan (0..6) untuk pembayar dividen rutin (pakai DY master, murah)."""
    m = master_data.metrics(ticker) or {}
    dy = m.get("dividend_yield")
    if not dy:
        return 0.0
    # DY 3% → +1.5 ; 6% → +3 ; ≥10% → +6 (dibatasi)
    return round(min(6.0, dy * 0.6), 2)


def should_defer_sell(prof: dict, pnl_pct: float, hard_exit: bool) -> Optional[dict]:
    """Tunda SELL demi dividen bila aman. hard_exit=True (cut-loss/AVOID) → JANGAN tunda."""
    up = prof.get("upcoming") or {}
    if hard_exit or not up.get("expected"):
        return None
    days = up.get("days_until")
    ey = up.get("event_yield_pct")
    if days is None or days < 0 or days > DEFER_WINDOW_DAYS:
        return None
    if ey is None or ey < MIN_EVENT_YIELD_PCT:
        return None
    # syarat: kerugian berjalan tidak melebihi dividen yang diharapkan (buffer)
    if pnl_pct is not None and pnl_pct <= -ey:
        return None
    return {"ex_date": up.get("ex_date"), "amount": up.get("amount"),
            "days_until": days, "event_yield_pct": ey, "source": up.get("source")}
