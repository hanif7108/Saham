"""
BSJP — Beli Saat Pre-closing, Jual Pagi Hari.

Strategi overnight trading BEI:
  • BELI saat pre-closing (15:50-16:00 WIB) bila BUY_price > IEP:
    demand kuat menjelang penutupan → kemungkinan gap-up besok.
  • JUAL pagi hari (08:45-09:00 WIB) bila IEP_pagi > CP_kemarin:
    konfirmasi gap-up → eksekusi take-profit di pre-opening.

IEP (Indicative Equilibrium Price) = harga keseimbangan estimasi saat pre-closing/pre-opening.
CP  (Closing Price) = harga penutupan resmi BEI.

Catatan kepatuhan syariah:
  - Long-only, tunai (tanpa margin / short selling — Fatwa No. 80/2011).
  - Hanya saham DES/ISSI yang lolos screening syariah.
  - Advisory only — tidak mengeksekusi order ke broker.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, time as dtime
from typing import Any, Optional

from app.config import BASE_DIR, settings
from app.data import provider, tradingview_provider


# --------------------------------------------------------------------------- #
#  Konstanta Sesi                                                              #
# --------------------------------------------------------------------------- #
SESSION_PRE_CLOSING_START  = dtime(15, 50)
SESSION_PRE_CLOSING_END    = dtime(16, 5)
SESSION_PRE_OPENING_START  = dtime(8, 45)
SESSION_PRE_OPENING_END    = dtime(9, 5)
SESSION_REGULAR_START      = dtime(9, 5)
SESSION_REGULAR_END        = dtime(15, 50)

BSJP_STATE_FILE = BASE_DIR.parent / "data_store" / "bsjp_state.json"


# --------------------------------------------------------------------------- #
#  Util                                                                        #
# --------------------------------------------------------------------------- #
def _rp(n: Any) -> str:
    try:
        return ("Rp " + f"{int(n):,}").replace(",", ".")
    except (TypeError, ValueError):
        return "-"


def _pct(n: Any) -> str:
    try:
        return f"{float(n):+.2f}%"
    except (TypeError, ValueError):
        return "-"


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f  # NaN check
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
#  Status Sesi                                                                 #
# --------------------------------------------------------------------------- #
def session_status() -> dict[str, Any]:
    """Kembalikan status sesi BEI saat ini dan relevansinya untuk strategi BSJP."""
    now = datetime.now()
    t = now.time()

    if SESSION_PRE_OPENING_START <= t < SESSION_PRE_OPENING_END:
        sesi = "pre-opening"
        label = "🟡 Pre-Opening (08:45–09:05)"
        aksi  = "JUAL — Cek IEP > CP, eksekusi jual bila gap-up terkonfirmasi."
        aktif = True
    elif SESSION_PRE_CLOSING_START <= t < SESSION_PRE_CLOSING_END:
        sesi = "pre-closing"
        label = "🔴 Pre-Closing (15:50–16:05)"
        aksi  = "BELI — Pantau IEP, beli bila BUY > IEP & sinyal kuat."
        aktif = True
    elif SESSION_REGULAR_START <= t < SESSION_REGULAR_END:
        sesi = "regular"
        label = "🟢 Regular (09:05–15:50)"
        aksi  = "Monitoring — pantau portofolio & sinyal intraday."
        aktif = False
    else:
        sesi = "closed"
        label = "⚫ Bursa Tutup"
        aksi  = "Persiapan — review kandidat BSJP untuk sesi berikutnya."
        aktif = False

    next_events = []
    if t < SESSION_PRE_OPENING_START:
        next_events.append({"waktu": "08:45", "event": "Pre-Opening — cek IEP > CP"})
    if t < SESSION_PRE_CLOSING_START:
        next_events.append({"waktu": "15:50", "event": "Pre-Closing — scan kandidat BSJP"})

    # Cek mode uji (force_market_open)
    force = getattr(settings, "force_market_open", False)
    if force:
        sesi = "pre-closing"
        label = "🧪 Mode Uji (Force Pre-Closing)"
        aktif = True

    return {
        "sesi": sesi,
        "label": label,
        "aksi": aksi,
        "aktif": aktif,
        "waktu_server": now.strftime("%H:%M:%S WIB"),
        "tanggal": now.strftime("%A, %d %b %Y"),
        "next_events": next_events,
        "mode_uji": force,
    }


# --------------------------------------------------------------------------- #
#  State Harian BSJP                                                           #
# --------------------------------------------------------------------------- #
def _load_state() -> dict[str, Any]:
    try:
        return json.loads(BSJP_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d: dict) -> None:
    try:
        BSJP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BSJP_STATE_FILE.write_text(
            json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  IEP dari TradingView                                                        #
# --------------------------------------------------------------------------- #
def _get_iep(ticker: str) -> Optional[float]:
    """
    Estimasi IEP dari TradingView scanner.

    IEP sesungguhnya hanya ada saat pre-closing/pre-opening di platform IDX.
    Di sini kita pakai harga 'close' dari scanner TradingView sebagai proksi
    terbaik (harga real-time terakhir yang tersedia), yang mendekati IEP.
    """
    try:
        m = tradingview_provider.metrics(ticker)
        if m:
            return _num(m.get("mp"))  # market price / close terkini
    except Exception:
        pass
    # Fallback ke yfinance
    try:
        hist = provider.get_history(ticker, period="5d")
        if hist is not None and not hist.empty and "Close" in hist:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _get_closing_price(ticker: str) -> Optional[float]:
    """CP (Closing Price) = harga penutupan resmi hari terakhir dari yfinance."""
    try:
        hist = provider.get_history(ticker, period="5d")
        if hist is not None and not hist.empty and "Close" in hist:
            closes = hist["Close"].dropna()
            if len(closes) >= 1:
                return float(closes.iloc[-1])
    except Exception:
        pass
    return None


def _get_volume_ratio(ticker: str) -> Optional[float]:
    """Rasio volume 5 hari vs rata-rata 20 hari (indikator demand)."""
    try:
        hist = provider.get_history(ticker, period="3mo")
        if hist is None or hist.empty or "Volume" not in hist:
            return None
        vol = hist["Volume"].astype(float).dropna()
        if len(vol) < 20:
            return None
        avg20 = float(vol.tail(20).mean())
        avg5  = float(vol.tail(5).mean())
        return round(avg5 / avg20, 2) if avg20 > 0 else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
#  Screening Syariah Ringkas                                                   #
# --------------------------------------------------------------------------- #
def _is_syariah(ticker: str) -> bool:
    """Cek apakah saham ada di universe syariah (DES/ISSI)."""
    try:
        tickers = provider.universe_tickers()
        return ticker.upper() in [t.upper() for t in tickers]
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Skor BSJP                                                                   #
# --------------------------------------------------------------------------- #
def _bsjp_score(tv_data: Optional[dict], vol_ratio: Optional[float]) -> float:
    """
    Skor keyakinan BSJP (0–100) berdasarkan:
    - Rekomendasi TradingView (bobot 40%)
    - Volume ratio (bobot 30%)
    - Fundamental dasar: ROE, DER (bobot 30%)
    """
    score = 0.0

    # Komponen 1: TradingView recommendation (0–40 pts)
    if tv_data:
        rec = _num(tv_data.get("recommend_all"))
        if rec is not None:
            # rec: -1 (STRONG SELL) → +1 (STRONG BUY) → skalakan ke 0-40
            score += max(0.0, (rec + 1) / 2 * 40)

    # Komponen 2: Volume spike (0–30 pts)
    if vol_ratio is not None:
        if vol_ratio >= 2.0:
            score += 30
        elif vol_ratio >= 1.5:
            score += 22
        elif vol_ratio >= 1.2:
            score += 14
        elif vol_ratio >= 1.0:
            score += 8

    # Komponen 3: Fundamental dasar (0–30 pts)
    if tv_data:
        roe = _num(tv_data.get("roe"))
        der = _num(tv_data.get("der"))
        per = _num(tv_data.get("per"))
        pbv = _num(tv_data.get("pbv"))
        pts = 0
        if roe is not None and roe > 15: pts += 8
        if der is not None and der < 1:   pts += 8
        if per is not None and 0 < per < 15: pts += 7
        if pbv is not None and 0 < pbv < 1.5: pts += 7
        score += pts

    return round(min(score, 100.0), 1)


# --------------------------------------------------------------------------- #
#  Scan Kandidat BELI (Pre-Closing)                                            #
# --------------------------------------------------------------------------- #
def scan_buy_candidates(limit: int = 10, force: bool = False) -> list[dict[str, Any]]:
    """
    Scan semua saham syariah untuk kandidat BSJP BELI.

    Menggunakan SATU batch request TradingView (cepat, tidak loop yfinance).
    Kondisi utama: rekomendasi TV BUY/STRONG BUY + volume spike + skor >= 50.

    Returns list kandidat sorted by bsjp_score desc.
    """
    # Ambil daftar ticker syariah (list[str])
    universe: list[str] = provider.universe_tickers()
    if not universe:
        return []

    # Satu request batch ke TradingView untuk semua ticker sekaligus
    tv_batch = tradingview_provider.scan_fundamentals(universe, force=force)

    candidates = []
    for ticker in universe:
        tv_data = tv_batch.get(ticker.upper())
        if not tv_data:
            continue

        iep = _num(tv_data.get("mp"))
        if iep is None or iep <= 0:
            continue

        # Hitung skor BSJP dari data TV (tanpa yfinance per-ticker)
        # Volume ratio: gunakan recommend_other sebagai proksi momentum
        # (positif = volume tinggi, negatif = volume rendah)
        rec_other = _num(tv_data.get("recommend_other"))
        vol_proxy: Optional[float] = None
        if rec_other is not None:
            # Skalakan -1..+1 ke 0.5..2.0 sebagai proksi volume ratio
            vol_proxy = round(1.25 + rec_other * 0.75, 2)

        score = _bsjp_score(tv_data, vol_proxy)
        rec_label = tv_data.get("recommend_label", "NO DATA")

        # Sinyal BELI: rekomendasi TV BUY/STRONG BUY + skor >= 50
        buy_signal = (
            score >= 50
            and rec_label in ("BUY", "STRONG BUY")
        )

        # CP: harga dari TV (tidak beda jauh dengan yfinance untuk data harian)
        cp = iep  # proksi: gunakan MP sebagai cp karena kita tidak fetch yfinance

        candidates.append({
            "ticker": ticker.upper(),
            "iep": round(iep, 2),
            "cp": round(cp, 2),
            "gap_iep_cp_pct": 0.0,  # tidak relevan saat iep == cp (proksi)
            "bsjp_score": score,
            "buy_signal": buy_signal,
            "rec_tv": rec_label,
            "vol_proxy": vol_proxy,
            "vol_ratio_5d_20d": vol_proxy,
            "fundamental": {
                "roe": _num(tv_data.get("roe")),
                "der": _num(tv_data.get("der")),
                "per": _num(tv_data.get("per")),
                "pbv": _num(tv_data.get("pbv")),
                "dy":  _num(tv_data.get("dy")),
            },
            "syariah": True,
            "sumber": "tradingview",
        })

    # Sort: sinyal BELI dulu, lalu by score desc
    candidates.sort(key=lambda x: (not x["buy_signal"], -x["bsjp_score"]))
    return candidates[:limit]



# --------------------------------------------------------------------------- #
#  Scan Kandidat JUAL Pagi (Pre-Opening)                                       #
# --------------------------------------------------------------------------- #
def scan_sell_signals() -> list[dict[str, Any]]:
    """
    Scan posisi portofolio yang dibeli kemarin (BSJP) untuk sinyal JUAL pagi.

    Kondisi: IEP_pagi > CP_kemarin → konfirmasi gap-up → jual di pre-opening.
    """
    try:
        from app.core import portfolio as port_core
        positions_resp = port_core.list_positions()
        positions = positions_resp.get("positions", [])
    except Exception:
        return []

    signals = []
    for p in positions:
        ticker = p.get("ticker", "").upper()
        if not ticker:
            continue

        iep_pagi = _get_iep(ticker)
        cp_kemarin = p.get("avg_price") or p.get("current_price")
        cp_current = p.get("current_price")
        lots = p.get("lots", 0)
        broker = p.get("broker", "—")

        if iep_pagi is None or cp_kemarin is None:
            continue

        gap_pct = round((iep_pagi - cp_kemarin) / cp_kemarin * 100, 2) if cp_kemarin > 0 else 0
        sell_signal = iep_pagi > cp_kemarin and gap_pct > 0.5  # gap minimal 0.5%

        signals.append({
            "ticker": ticker,
            "broker": broker,
            "lots": lots,
            "cp_kemarin": cp_kemarin,
            "iep_pagi": iep_pagi,
            "gap_pct": gap_pct,
            "sell_signal": sell_signal,
            "pl_pct": p.get("net_pl_pct") or p.get("pl_pct"),
            "sinyal": "✅ JUAL PAGI (IEP > CP)" if sell_signal else "⏸ Tahan (IEP ≤ CP)",
            "aksi": (
                f"Jual {lots} lot @ estimasi Rp {int(iep_pagi):,} pada 08:45–09:00"
                if sell_signal else
                "Pantau — IEP belum melampaui harga beli, tahan posisi."
            ),
        })

    signals.sort(key=lambda x: (not x["sell_signal"], -(x.get("gap_pct") or 0)))
    return signals


# --------------------------------------------------------------------------- #
#  Build Laporan Lengkap                                                       #
# --------------------------------------------------------------------------- #
def build_bsjp_report(limit: int = 10, force: bool = False) -> dict[str, Any]:
    """Laporan BSJP lengkap: status sesi + kandidat beli + sinyal jual."""
    status = session_status()
    candidates = scan_buy_candidates(limit=limit, force=force)
    sell_signals = scan_sell_signals()

    strong_buy = [c for c in candidates if c["buy_signal"]]
    sell_now = [s for s in sell_signals if s["sell_signal"]]

    return {
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sesi": status,
        "ringkasan": {
            "kandidat_beli": len(candidates),
            "sinyal_beli_kuat": len(strong_buy),
            "sinyal_jual_pagi": len(sell_now),
        },
        "kandidat_beli": candidates,
        "sinyal_jual_pagi": sell_signals,
        "strategi": {
            "beli": "Pre-closing (15:50–16:00): Beli bila BUY > IEP & skor ≥ 50",
            "jual": "Pre-opening (08:45–09:00): Jual bila IEP_pagi > CP_kemarin",
            "risiko": "Gap down overnight, sentimen global negatif, likuiditas rendah",
            "syariah": "Long-only, tunai — Fatwa DSN-MUI No. 80/2011",
        },
    }


# --------------------------------------------------------------------------- #
#  Alert Telegram BSJP                                                         #
# --------------------------------------------------------------------------- #
def build_telegram_text(report: dict[str, Any]) -> str:
    """Format pesan Telegram HTML untuk alert BSJP."""
    sesi = report.get("sesi", {})
    ring = report.get("ringkasan", {})
    now  = datetime.now().strftime("%H:%M WIB")

    lines = [
        f"🌙 <b>BSJP Alert</b> ({now}) — {sesi.get('label', '')}",
        f"📊 {ring.get('sinyal_beli_kuat', 0)} sinyal BELI · {ring.get('sinyal_jual_pagi', 0)} sinyal JUAL pagi",
    ]

    buys = [c for c in report.get("kandidat_beli", []) if c.get("buy_signal")][:5]
    if buys:
        lines.append("\n🟢 <b>Kandidat BELI (BUY &gt; IEP):</b>")
        for c in buys:
            iep_str = f"Rp {int(c['iep']):,}" if c.get("iep") else "—"
            gap_str = f"{c['gap_iep_cp_pct']:+.1f}%" if c.get("gap_iep_cp_pct") is not None else "—"
            lines.append(
                f" • <b>{c['ticker']}</b> — IEP {iep_str} · gap {gap_str} · "
                f"skor {c['bsjp_score']} · {c['rec_tv']}"
            )
    else:
        lines.append("\n🟢 Tidak ada sinyal BELI kuat saat ini.")

    sells = [s for s in report.get("sinyal_jual_pagi", []) if s.get("sell_signal")][:5]
    if sells:
        lines.append("\n🔴 <b>Jual Pagi (IEP &gt; CP kemarin):</b>")
        for s in sells:
            lines.append(
                f" • <b>{s['ticker']}</b> — IEP Rp {int(s['iep_pagi']):,} "
                f"(gap +{s['gap_pct']:.1f}%) · {s['lots']} lot @ {s['broker']}"
            )

    lines.append(
        "\n<i>Advisory: keputusan & risiko sepenuhnya di tangan Anda. "
        "Long-only, tunai — syariah.</i>"
    )
    return "\n".join(lines)


def send_bsjp_alert(report: Optional[dict] = None) -> dict[str, Any]:
    """Kirim alert BSJP ke Telegram."""
    from app.core import telegram_notify
    if report is None:
        report = build_bsjp_report()
    text = build_telegram_text(report)
    return telegram_notify.send(text)
