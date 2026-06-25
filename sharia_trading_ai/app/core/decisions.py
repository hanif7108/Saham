"""
Mesin Pusat Keputusan — port decision.py app lama (Mac Mini).

Menghasilkan daftar BUY / HOLD / SELL portfolio-aware:
  - Top-5 pilihan (rank by fundamental*2 + technical)
  - Radar prospects (volume spike >= 1.5x)
  - decide_for_watchlist (calon BELI) & decide_for_portfolio (posisi dimiliki)

Disederhanakan dari app lama: tanpa saldo broker RDN / compounding 18-langkah;
alokasi memakai persentase generik dari trading fund.
"""

from __future__ import annotations

from typing import Any, Optional

import math
from datetime import datetime

from app.config import MM, settings
from app.core import accounts, bei_calendar, dividend, funnel, portfolio, roi, undervalue
from app.data import provider

CUT_LOSS_PCT = -7.0      # SELL bila P/L <= -7%
TAKE_PROFIT_PCT = 20.0   # SELL bila P/L >= +20%
BASE_TARGET_PCT = 7.0    # target profit dasar (Jalur 7%)

INVESTASI_TICKERS = {"ASII", "SIDO"}

def _nudge_investasi(res: Optional[dict], tk: str) -> Optional[dict]:
    if not res:
        return res
    if tk in INVESTASI_TICKERS:
        res["investasi_nudge"] = True
        res["reason"] = "🌟 [INVESTASI TAHUNAN] " + res["reason"]
        res["next_step"] = (
            f"Saham {tk} direkomendasikan untuk Investasi Tahunan (Portofolio Investasi Saham). "
            f"Bila membeli untuk investasi, gunakan volume lebih besar (misal 5-10x) untuk menangkap dividen & capital gain. "
            f"Trading harian tetap berjalan paralel dengan volume terpisah. "
            f"Rekomendasi taktis: {res['next_step']}"
        )
    return res


# ---------------- Skor kekuatan (untuk strategi N-emiten) ---------------- #
def _hold_strength(p: dict, ri: dict, top5_lookup: dict[str, int]) -> float:
    """Kekuatan posisi dimiliki: fundamental*2 + teknikal + bonus Top5 + nudge P/L."""
    fs = ri.get("fundamental_score", 0) or 0
    ts = ri.get("technical_score", 0) or 0
    pnl = p.get("pnl", 0) or 0
    score = fs * 2 + ts
    rank = top5_lookup.get(p.get("ticker"))
    if rank:
        score += (6 - rank)                       # Top5: ke-1 +5 … ke-5 +1
    score += max(-3.0, min(3.0, pnl / 5.0))       # dorongan oleh P/L (dibatasi ±3)
    return round(score, 2)


def _cand_strength(s: dict, top5_lookup: dict[str, int]) -> float:
    """Kekuatan kandidat BELI: fundamental*2 + teknikal + bonus Top5 + pola Jalur 7%."""
    fs = s.get("fundamental_score", 0) or 0
    ts = s.get("technical_score", 0) or 0
    score = fs * 2 + ts
    rank = top5_lookup.get(s.get("ticker"))
    if rank:
        score += (6 - rank)
    _, breaker, kandang = _j7_active(s)
    if breaker or kandang:
        score += 2
    return round(score, 2)


# ---------------- Top 5 ---------------- #
def get_top5_ordered(ranking: list[dict]) -> list[str]:
    cands = []
    for s in ranking:
        if (s.get("current_price") or 0) <= 0 or s.get("fundamental_label") == "AVOID":
            continue
        fs = s.get("fundamental_score") or 0
        ts = s.get("technical_score") or 0
        cands.append(((fs * 2) + ts, fs, ts, s["ticker"]))
    cands.sort(reverse=True)
    return [c[3] for c in cands[:5]]


def _j7_active(s: dict) -> tuple[list[str], bool, bool]:
    sig = (s.get("jalur7") or {}).get("signals", {}) if isinstance(s.get("jalur7"), dict) else {}
    def act(k):
        return bool(sig.get(k, {}).get("pass")) if isinstance(sig, dict) else False
    names = {"breaker": "Breaker", "kandang_kuda": "Kandang Kuda",
             "shadow": "Shadow Rejection", "swing_line": "Swing Line"}
    patterns = [v for k, v in names.items() if act(k)]
    return patterns, act("breaker"), act("kandang_kuda")


def _alloc(pct: float) -> str:
    return f"Alokasikan {pct:.0f}% dari trading fund (uang dingin)."


def _fibonacci_suffix(fib: Optional[dict]) -> str:
    if not fib:
        return ""
    closest_note = fib.get("closest_level_note", "")
    next_cycle = None
    for cyc in fib.get("time_cycles", []):
        if cyc.get("days_left") is not None and cyc["days_left"] >= 0:
            if next_cycle is None or cyc["days_left"] < next_cycle["days_left"]:
                next_cycle = cyc
    
    note = ""
    if closest_note and "Bergerak" not in closest_note:
        note = closest_note.replace("Menguji Golden ", "").replace("Menguji ", "").split(" (")[0]
        
    cycle_str = ""
    if next_cycle:
        days_left = next_cycle["days_left"]
        days_str = "hari ini" if days_left == 0 else f"{days_left} hari bursa lagi"
        cycle_str = f"reversal {next_cycle['date']} ({days_str})"
        
    parts = []
    if note:
        parts.append(note)
    if cycle_str:
        parts.append(cycle_str)
        
    if parts:
        return " · " + " · ".join(parts)
    return ""


# ---------------- Watchlist (calon BELI) ---------------- #
def decide_for_watchlist(s: dict, prospects_set: set, top5_lookup: dict[str, int]) -> Optional[dict]:
    tk = s.get("ticker")
    if s.get("trend") == "DOWNTREND":
        return None
    
    # Gerbang Penyaring Akhir Bandarmologi (Smart Money)
    from app.core import bandarmologi
    bandar = bandarmologi.get_bandar_analysis(tk)
    if not bandar.get("layak_beli", True):
        return None
    fs = s.get("fundamental_score") or 0
    fmax = s.get("fundamental_max") or 7
    f_label = s.get("fundamental_label") or ""
    t_signal = s.get("technical_signal") or "HOLD"
    rsi = s.get("rsi") or 50
    ma_cross = s.get("ma_cross") or "DEATH"
    sector = s.get("sector") or ""
    in_radar = tk in prospects_set
    rank_num = top5_lookup.get(tk)
    patterns, breaker, kandang = _j7_active(s)
    suffix = f" [Jalur 7%: {', '.join(patterns)} aktif]" if patterns else ""
    tgt = "Target profit min 7%"

    fib = s.get("fibonacci")
    fibo_suffix = _fibonacci_suffix(fib)

    def make(action, urg, conf, reason, alloc_pct, ret_mult, ctx="WATCHLIST"):
        return {"action": action, "ticker": tk, "urgency": urg, "confidence": conf,
                "context": ctx, "reason": reason + fibo_suffix,
                "details": {"sector": sector, "rsi": rsi, "score": fs, "css": s.get("css")},
                "expected_return_pct": round(BASE_TARGET_PCT * ret_mult, 2),
                "next_step": f"{_alloc(alloc_pct)} {tgt}."}

    if rank_num is not None:
        if t_signal == "BUY":
            return make("BUY", "HIGH", "HIGH", f"Top 5 Pilihan (Ke-{rank_num}) + Momentum — Fund {fs}/{fmax} + Sinyal BUY{suffix}", 20, 1.5)
    if fs >= 4 and (breaker or kandang):
        pat = " & ".join([p for p in ["Breaker", "Kandang Kuda"] if (p == "Breaker" and breaker) or (p == "Kandang Kuda" and kandang)])
        return make("BUY", "HIGH", "HIGH", f"Jalur 7% Setup ({pat}) — Fund {fs}/{fmax} + pola aktif!{suffix}", 15, 1.5)
    if fs >= 4 and t_signal == "BUY" and in_radar and rsi < 60 and ma_cross == "GOLDEN":
        return make("BUY", "HIGH", "HIGH", f"Strong Setup — Fund {fs}/{fmax} + Tech BUY + Volume spike + Golden cross{suffix}", 15, 1.3)
    if fs >= 4 and rsi < 30 and ma_cross == "GOLDEN":
        return make("BUY", "MEDIUM", "HIGH", f"Oversold Gem — Fund {fs}/{fmax} + RSI {rsi:.1f} (bottom?) + Golden{suffix}", 15, 1.4)
    if fs >= 4 and t_signal == "BUY":
        return make("BUY", "MEDIUM", "MEDIUM", f"Quality + Momentum — Fund {fs}/{fmax} + Tech BUY{suffix}", 10, 1.0)
    if fs >= 3 and rsi < 30:
        return make("BUY", "LOW", "LOW", f"Speculative bottom — Fund {fs}/{fmax} + RSI {rsi:.1f}{suffix}", 5, 0.7)
    return None


# ---------------- Portfolio (posisi dimiliki) ---------------- #
def decide_for_portfolio(
    p: dict,
    ranking_lookup: dict[str, dict],
    top5_lookup: dict[str, int],
    take_profit_target: Optional[float] = None,
    min_buy_accuracy: Optional[float] = None,
    akurasi_pct: Optional[float] = None,
) -> Optional[dict]:
    tk = p.get("ticker")
    pnl = p.get("pnl", 0) or 0
    fs = p.get("fundamental_score", 0) or 0
    fmax = p.get("fundamental_max", 7) or 7
    t_signal = p.get("technical_signal", "HOLD")
    rsi = p.get("rsi") or 50
    ma_cross = p.get("ma_cross", "DEATH")
    ri = ranking_lookup.get(tk, {})
    f_label_real = ri.get("fundamental_label", "HOLD")
    patterns, breaker, kandang = _j7_active(ri)
    suffix = f" [Jalur 7%: {', '.join(patterns)} aktif]" if patterns else ""

    tp_target = take_profit_target if take_profit_target is not None else TAKE_PROFIT_PCT

    base = {"ticker": tk, "details": {"pnl": pnl, "score": fs, "rsi": rsi}}
    res = None
    if pnl <= CUT_LOSS_PCT:
        res = {**base, "action": "SELL", "urgency": "URGENT", "confidence": "HIGH", "context": "PORTFOLIO",
                "reason": f"CUT LOSS — P/L {pnl:.1f}% ≤ {CUT_LOSS_PCT}%", "next_step": "Jual hari ini untuk batasi kerugian."}
    elif pnl >= tp_target:
        res = {**base, "action": "SELL", "urgency": "URGENT", "confidence": "HIGH", "context": "PORTFOLIO",
                "reason": f"TAKE PROFIT — P/L +{pnl:.1f}% ≥ {tp_target}% (Target ROI)", "next_step": f"Realisasikan profit untuk mengamankan target ROI >{tp_target}%."}
    elif f_label_real == "AVOID":
        res = {**base, "action": "SELL", "urgency": "HIGH", "confidence": "MEDIUM", "context": "PORTFOLIO",
                "reason": f"Fundamental memburuk → AVOID (skor {fs}/{fmax})", "next_step": "Eksit perlahan walau belum kena cut-loss."}
    elif t_signal == "SELL" and pnl < 0 and ma_cross == "DEATH":
        res = {**base, "action": "SELL", "urgency": "MEDIUM", "confidence": "MEDIUM", "context": "PORTFOLIO",
                "reason": f"Tech SELL + Death cross + P/L {pnl:.1f}%", "next_step": "Pertimbangkan exit jika besok masih melemah."}
    else:
        # Sinkronisasi ROI: Hanya ijinkan tambah/average down bila akurasi memenuhi ambang adaptif
        allow_buy = True
        if min_buy_accuracy is not None and akurasi_pct is not None:
            if akurasi_pct < min_buy_accuracy:
                allow_buy = False

        # Gerbang Penyaring Akhir Bandarmologi (Smart Money)
        if allow_buy:
            from app.core import bandarmologi
            bandar = bandarmologi.get_bandar_analysis(tk)
            if not bandar.get("layak_beli", True):
                allow_buy = False

        if allow_buy and fs >= 4 and t_signal == "BUY" and pnl >= -3:
            res = {**base, "action": "BUY", "urgency": "MEDIUM", "confidence": "HIGH", "context": "PORTFOLIO_ADD",
                    "reason": f"Add posisi — Fund {fs}/{fmax} + Tech BUY{suffix}", "next_step": _alloc(10) + " untuk tambah posisi."}
        elif allow_buy and fs >= 4 and rsi < 30:
            res = {**base, "action": "BUY", "urgency": "MEDIUM", "confidence": "HIGH", "context": "PORTFOLIO_AVG_DOWN",
                    "reason": f"Average down — Fund {fs}/{fmax} + RSI {rsi:.1f} (oversold){suffix}", "next_step": _alloc(15) + " untuk average down."}
        else:
            rank_num = top5_lookup.get(tk)
            if rank_num is not None:
                res = {**base, "action": "HOLD", "urgency": "LOW", "confidence": "HIGH", "context": "PORTFOLIO_HOLD",
                        "reason": f"P/L {pnl:+.1f}% — Top 5 (Ke-{rank_num}), pertahankan posisi.", "next_step": "Simpan (HOLD) pilihan utama ini."}
            else:
                res = {**base, "action": "HOLD", "urgency": "LOW", "confidence": "MEDIUM", "context": "PORTFOLIO_HOLD",
                        "reason": f"P/L {pnl:+.1f}% — Fundamental & teknikal stabil.", "next_step": f"Terus simpan (HOLD) {tk}."}

    if res:
        fib = ri.get("fibonacci")
        res["reason"] = res["reason"] + _fibonacci_suffix(fib)
    return res


# ---------------- Ranking + agregator ---------------- #
def build_ranking(limit: Optional[int] = None) -> list[dict]:
    tickers = funnel.provider.universe_tickers()
    if limit:
        tickers = tickers[:limit]
    ranking: list[dict] = []
    
    from concurrent.futures import ThreadPoolExecutor
    
    # Pra-muat data indeks IHSG sekali agar tidak terjadi file lock saat menulis cache
    funnel.provider.get_index_history()
    
    def analyze(t):
        try:
            return funnel.analyze_stock(t)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze, tickers))

    for rep in results:
        if rep is None or not rep["sharia"]["compliant"]:
            continue
        sig = rep.get("signal", {}) or {}
        ranking.append({
            "ticker": rep["ticker"], "sector": rep.get("sector"),
            "current_price": rep.get("technical", {}).get("price") or sig.get("last_close") or 0,
            "fundamental_score": rep["canslim"]["canslim_score"],
            "fundamental_max": 7,
            "magic_score": rep["fundamental"].get("magic_score"),
            "fundamental_label": rep["fundamental"].get("fundamental_label"),
            "technical_score": sig.get("score", 0),
            "technical_signal": sig.get("signal", "HOLD"),
            "ma_cross": sig.get("ma_cross", "DEATH"),
            "rsi": sig.get("rsi") or 50,
            "volume_spike": sig.get("volume_spike"),
            "jalur7": rep.get("jalur7", {}),
            "final_signal": rep["rekomendasi"].get("final_signal"),
            "css": rep["rekomendasi"].get("css"),
            "skor": rep["rekomendasi"].get("skor"),
            "trend": rep.get("technical", {}).get("trend", "SIDEWAYS"),
            "fibonacci": rep.get("technical", {}).get("fibonacci"),
        })
    return ranking


_URG = {"URGENT": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
_CONF = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


# ---------------- Pengayaan: akurasi prediksi + alokasi Money Management ---------------- #
def _alloc_buy(tk: str, price: Optional[float], pos_by_tk: dict[str, dict],
               rdn_list: list[dict], assigned_broker: Optional[str] = None) -> dict[str, Any]:
    """Saran alokasi BELI: pakai RDN yang ditetapkan (per-RDN); jika tak ada, pilih
    RDN dgn cash + slot kosong. Hitung lot/Rp/%cash, risk/target."""
    pos = pos_by_tk.get(tk)
    target_rdn = None
    if assigned_broker:
        target_rdn = next((r for r in rdn_list if r["broker"] == assigned_broker), None)
    if target_rdn is None and pos and pos.get("broker"):
        target_rdn = next((r for r in rdn_list if r["broker"] == pos["broker"]), None)
    if target_rdn is None:
        cand = [r for r in rdn_list if r["advice"]["open_slots"] > 0 and r["cash"] > 0]
        cand.sort(key=lambda r: r["cash"], reverse=True)
        target_rdn = cand[0] if cand else None
    if not target_rdn:
        return {"tipe": "beli", "catatan": "Belum ada RDN dengan cash & slot kosong — isi saldo cash RDN dulu."}
    adv = target_rdn["advice"]
    bid = adv.get("per_emiten") or 0
    cash = target_rdn["cash"] or 0
    fb = target_rdn.get("fee_buy_pct") or 0
    fs = target_rdn.get("fee_sell_pct") or 0
    # lot dihitung agar (harga×lembar + biaya beli) muat dalam bid
    lots = int(bid // (price * 100 * (1 + fb / 100))) if (price and price > 0) else 0
    shares_val = round(lots * price * 100) if (price and lots > 0) else 0
    buy_fee = round(shares_val * fb / 100)
    outlay = shares_val + buy_fee                          # total kas keluar (termasuk biaya beli)
    rp = adv.get("risk_pct") or 0
    pp = adv.get("profit_pct") or 0
    roundtrip = round(fb + fs, 3)
    return {
        "tipe": "beli", "rdn": target_rdn["broker"], "bid_idr": bid,
        "lots": lots, "nilai_idr": shares_val, "buy_fee_idr": buy_fee, "outlay_idr": outlay,
        "pct_cash": round(outlay / cash * 100, 1) if cash else None,
        "risk_pct": rp, "risk_idr": round(shares_val * rp / 100),
        "profit_pct": pp, "target_idr": round(shares_val * pp / 100),
        "fee_buy_pct": fb, "fee_sell_pct": fs, "roundtrip_pct": roundtrip,
        "net_target_pct": round(pp + roundtrip, 2),       # kenaikan harga minimal utk profit BERSIH
        "catatan": (f"Beli ~{lots} lot @ {target_rdn['broker']} ≈ Rp {outlay:,} (incl. biaya {buy_fee:,}) · "
                    f"jual +{round(pp + roundtrip, 2)}% utk profit {pp}% bersih".replace(",", ".")
                    if lots > 0 else f"Cash {target_rdn['broker']} kurang untuk 1 lot (bid Rp {bid:,})".replace(",", ".")),
    }


def _exit_plan(pos: dict, reason: str, context: str) -> dict[str, Any]:
    """Rencana JUAL bertahap: berapa lot per tahap + patokan harga, sesuai jenis exit."""
    lots = int(pos.get("lots") or 0)
    avg = pos.get("avg_price") or 0
    cur = pos.get("current_price")
    be = pos.get("break_even") or round(avg) if avg else None
    pnl = pos.get("net_pl_pct")
    cut = round(avg * (1 + CUT_LOSS_PCT / 100)) if avg else None     # harga cut-loss -7%
    r = reason or ""
    hard_cut = "CUT LOSS" in r or (pnl is not None and pnl <= CUT_LOSS_PCT)
    take_profit = "TAKE PROFIT" in r or (pnl is not None and pnl >= TAKE_PROFIT_PCT)
    decisive = context in ("ROTATION_OUT", "PORTFOLIO_TRIM")

    if hard_cut:
        frac, style = 1.0, "JUAL SEMUA sekarang (cut-loss — batasi rugi)"
    elif decisive:
        frac, style = 1.0, "JUAL SEMUA (rotasi/pangkas — bebaskan slot utk emiten lebih kuat)"
    elif take_profit:
        frac, style = 0.5, "Realisasi sebagian, sisanya biarkan berjalan (trailing)"
    else:                                                            # AVOID / sinyal teknikal → perlahan
        frac, style = 0.5, "Eksit BERTAHAP (front-loaded) — fundamental/teknikal melemah"

    lots_now = min(lots, max(1, math.ceil(lots * frac))) if lots else 0
    lots_rest = lots - lots_now

    _, fee_sell = accounts.fees_for(pos.get("broker"))    # nilai jual = bersih setelah biaya jual

    def _v(n_lots: int, price: Optional[float]) -> dict:
        if not price or not n_lots:
            return {"harga": None, "nilai": None, "nilai_net": None}
        gross = round(n_lots * MM.SHARES_PER_LOT * price)
        return {"harga": round(price), "nilai": gross,
                "nilai_net": round(gross * (1 - fee_sell / 100))}

    stages = [{"tahap": 1, "lots": lots_now, "kapan": "sekarang",
               "patokan": "harga pasar (eksekusi saat jam bursa)", **_v(lots_now, cur)}]
    if lots_rest > 0:
        if take_profit:
            stages.append({"tahap": 2, "lots": lots_rest, "kapan": "trailing",
                           "patokan": "biarkan berjalan; jual bila berbalik arah / trailing stop kena",
                           **_v(lots_rest, cur)})
        else:
            stages.append({"tahap": 2, "lots": lots_rest, "kapan": "bertahap",
                           "patokan": f"jual bila pantul ≥ {be} (impas), ATAU cut bila ≤ {cut} (−7%)",
                           "skenario_impas": _v(lots_rest, be), "skenario_cut": _v(lots_rest, cut)})
    total_now = _v(lots, cur)                              # bila dijual semua di harga sekarang
    return {"lots_total": lots, "lots_now": lots_now, "lots_rest": lots_rest,
            "cut_loss_price": cut, "breakeven_price": be, "fee_sell_pct": fee_sell,
            "total_nilai_now": total_now["nilai"],         # kotor (sebelum fee)
            "total_nilai_net_now": total_now["nilai_net"], "style": style, "stages": stages}


def _enrich(recs: list[dict], pos_by_tk: dict[str, dict], rdn_list: list[dict],
            cache: Optional[dict] = None) -> None:
    """Tambahkan akurasi prediksi (win-rate backtest), skor undervalue, & alokasi MM."""
    cache = cache if cache is not None else {}
    for d in recs:
        tk = d.get("ticker")
        if tk in ("🪙 EMAS", "EMAS"):
            continue
        price = None
        uv = _accuracy(tk, cache)
        if uv:
            bt = uv.get("backtest") or {}
            d["akurasi_pct"] = bt.get("win_rate")
            d["akurasi_n"] = bt.get("n_signals")
            d["uv_score"] = uv.get("score")
            d["expected_return_pct"] = d.get("expected_return_pct") or uv.get("expected_return_pct")
            price = uv.get("price")
        if d.get("action") == "BUY":
            d["alokasi"] = _alloc_buy(tk, price, pos_by_tk, rdn_list, d.get("alokasi_rdn"))
        elif d.get("action") == "SELL":
            pos = pos_by_tk.get(tk)
            if pos:
                d["alokasi"] = {"tipe": "realisasi", "rdn": pos.get("broker"),
                                "nilai": pos.get("value"), "nilai_net": pos.get("net_value"),
                                "lots": pos.get("lots")}
                d["exit_plan"] = _exit_plan(pos, d.get("reason", ""), d.get("context", ""))


def market_status() -> dict[str, Any]:
    """Status bursa REALTIME (waktu WIB) berdasar kalender libur BEI + jam sesi.

    open=True hanya saat jam perdagangan berjalan. `closed` (utk pelunakan sinyal)
    = BUKAN hari bursa (akhir pekan/libur) — bukan sekadar 'data basi', agar pagi
    hari bursa tidak salah ditandai libur.
    """
    from datetime import time as _time
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Jakarta"))         # paksa WIB, bebas-zona server
    except Exception:  # noqa: BLE001
        now = datetime.now()
    today = now.date()
    wd = now.weekday()
    weekend = wd >= 5
    holiday_name = bei_calendar.is_holiday(today)
    trading_day = not weekend and not holiday_name
    nt = now.time()

    open_t, close_t = _time(9, 0), _time(16, 0)              # pre-closing s/d 16:00
    s1_end, s2_start = (_time(11, 30), _time(14, 0)) if wd == 4 else (_time(12, 0), _time(13, 30))

    last_date = None
    try:
        df = provider.get_history("^JKSE", period="10d")
        if df is not None and not df.empty:
            last_date = df.index[-1].date()
    except Exception:  # noqa: BLE001
        pass

    if not trading_day:
        session, is_open = ("libur", False)
        reason = f"Libur bursa: {holiday_name}." if holiday_name else "Akhir pekan — bursa tutup."
    elif nt < open_t:
        session, is_open, reason = "pra-pembukaan", False, "Pra-pembukaan — bursa buka pukul 09:00 WIB."
    elif nt <= s1_end:
        session, is_open, reason = "sesi-1", True, "Bursa BUKA — Sesi I."
    elif nt < s2_start:
        session, is_open, reason = "istirahat", False, "Istirahat sesi — bursa jeda sejenak."
    elif nt <= close_t:
        session, is_open, reason = "sesi-2", True, "Bursa BUKA — Sesi II."
    else:
        session, is_open, reason = "pasca-penutupan", False, "Sesudah penutupan — bursa tutup hari ini."

    return {
        "trading_day": trading_day, "open": is_open, "session": session,
        "closed": not trading_day,                          # pelunakan sinyal: hanya libur/akhir pekan
        "weekend": weekend, "holiday": holiday_name, "reason": reason,
        "last_trading_date": str(last_date) if last_date else None,
        "next_holiday": bei_calendar.next_holiday(today),
        "now_wib": now.strftime("%a %Y-%m-%d %H:%M WIB"),
    }


def _accuracy(tk: str, cache: dict) -> Optional[dict]:
    if tk not in cache:
        try:
            cache[tk] = undervalue.evaluate(tk)
        except Exception:  # noqa: BLE001
            cache[tk] = None
    return cache[tk]


def _prime_pool(ranking: list[dict]) -> list[tuple[float, dict]]:
    """Pra-saring berdasar SKOR FUNNEL (6 Magic+CAN SLIM+teknikal+Jalur7) — IDENTIK
    dengan verdict di tab Analisa & Screening. Sumber Top-5 & kandidat."""
    pool = []
    for s in ranking:
        if (s.get("current_price") or 0) <= 0 or s.get("fundamental_label") == "AVOID":
            continue
        if s.get("trend") == "DOWNTREND":
            continue
        pool.append((float(s.get("skor") or 0), s))         # skor funnel 0-100
    pool.sort(key=lambda x: x[0], reverse=True)
    return pool


def _conviction(s: dict, uv: Optional[dict]) -> dict[str, Any]:
    """Skor keyakinan GABUNGAN yang menyatukan output ketiga tab (semua algoritma AI):
      • 40% SKOR FUNNEL (Analisa/Screening: 6 Magic+CAN SLIM+teknikal+Jalur7)
      • 30% SKOR UNDERVALUE (Screener Undervalue: valuasi+timing+backtest)
      • 30% AKURASI prediksi (win-rate backtest historis)
    """
    funnel_skor = float(s.get("skor") or 0)
    uv_score = uv.get("score") if uv else None
    acc = (uv.get("backtest") or {}).get("win_rate") if uv else None
    comps = {
        "funnel": (funnel_skor / 100, 0.40),
        "undervalue": (uv_score / 100 if uv_score is not None else None, 0.30),
        "akurasi": (acc / 100 if acc is not None else None, 0.30),
    }
    num = sum(v * w for v, w in comps.values() if v is not None)
    den = sum(w for v, w in comps.values() if v is not None)
    score = round(num / den * 100, 1) if den else 0.0
    # BONUS dividen: pembayar rutin = pendorong positif (aditif, dibatasi)
    div_bonus = dividend.dividend_bonus(s.get("ticker", ""))
    score = round(min(100.0, score + div_bonus), 1)
    return {"conviction": score, "funnel_skor": round(funnel_skor),
            "uv_score": uv_score, "akurasi_pct": acc, "dividend_bonus": div_bonus,
            "final_signal": s.get("final_signal"), "css": s.get("css")}


def build_decisions(limit: Optional[int] = None, target: Optional[int] = None,
                    force_open: Optional[bool] = None) -> dict[str, Any]:
    """Keputusan portfolio-aware dengan STRATEGI N-EMITEN TERKONSENTRASI.

    Tujuan: menjaga portofolio mingguan tepat `settings.target_holdings` emiten.
    Setiap rekomendasi diarahkan ke target tsb:
      • kurang dari target  → BELI prioritas-tinggi untuk isi slot kosong;
      • lebih dari target    → JUAL emiten terlemah (pangkas) sampai target;
      • penuh                 → ROTASI (tukar) bila ada kandidat jauh lebih kuat.
    Pemicu eksit wajib (cut-loss / take-profit / fundamental AVOID) tetap berlaku
    lebih dulu dan otomatis mengosongkan slot.
    """
    target = max(1, int(target if target is not None else settings.target_holdings))
    margin = float(settings.rotation_margin)
    test_mode = bool(force_open if force_open is not None else settings.force_market_open)

    ranking = build_ranking(limit)
    prospects_set = {s["ticker"] for s in ranking if (s.get("volume_spike") or 0) >= 1.5}
    ranking_lookup = {s["ticker"]: s for s in ranking}
    bursa = market_status()
    bursa["test_mode"] = test_mode      # Mode Uji: anggap bursa buka utk pengujian

    positions = portfolio.list_positions()["positions"]
    portfolio_set = {p["ticker"] for p in positions}

    # ---- Peringkat utama + akurasi prediksi — SATU sumber utk Top-5 & kandidat ---- #
    pool = _prime_pool(ranking)                 # pra-saring berdasar kekuatan (buang AVOID/no-price)
    acc_cache: dict[str, Optional[dict]] = {}
    for _, s in pool:                           # hitung akurasi utk seluruh pool
        _accuracy(s["ticker"], acc_cache)
    for p in positions:
        _accuracy(p["ticker"], acc_cache)

    def _acc_pct(tk):
        uv = acc_cache.get(tk)
        return (uv.get("backtest") or {}).get("win_rate") if uv else None

    # Skor keyakinan GABUNGAN (funnel + undervalue + akurasi) untuk semua di pool →
    # dipakai KONSISTEN oleh Top-5 DAN kolom BELI (semua algoritma AI menyatu).
    conv_map: dict[str, dict] = {}
    for _, s in pool:
        conv_map[s["ticker"]] = _conviction(s, acc_cache.get(s["ticker"]))
    # Urutkan berdasarkan prioritas tingkat akurasi trading (akurasi_pct), lalu conviction
    prime = sorted(pool, key=lambda kv: (
        conv_map[kv[1]["ticker"]]["akurasi_pct"] if conv_map[kv[1]["ticker"]]["akurasi_pct"] is not None else 0.0,
        conv_map[kv[1]["ticker"]]["conviction"]
    ), reverse=True)
    top5 = [s["ticker"] for _, s in prime[:5]]
    top5_lookup = {t: i + 1 for i, t in enumerate(top5)}

    # ---- Strategi ADAPTIF: target profit & ambang akurasi dari kinerja ROI (kejar 6%) ---- #
    adaptive = roi.adaptive_strategy(float(MM.PROFIT_FUND_PCT))
    min_acc = adaptive["min_buy_accuracy"]
    take_profit_target = adaptive["take_profit_net_pct"]

    buy, hold, sell = [], [], []

    # RDN yang dikenal (punya posisi atau saldo cash) + cash-nya
    brk = accounts.breakdown()
    rdn_cash = {r["broker"]: (r["cash"] or 0) for r in brk["rdn"]}

    # ---- 1. Evaluasi posisi: eksit-wajib vs keeper, DIKELOMPOKKAN per RDN ---- #
    keepers_by_rdn: dict[str, list] = {}
    for p in positions:
        ri = ranking_lookup.get(p["ticker"], {})
        pp = {**p, "pnl": p.get("pl_pct") or 0,
              "fundamental_score": ri.get("fundamental_score", 0), "fundamental_max": 7,
              "technical_signal": ri.get("technical_signal", "HOLD"),
              "rsi": ri.get("rsi", 50), "ma_cross": ri.get("ma_cross", "DEATH")}
        broker = p.get("broker") or "Tanpa RDN"
        d = decide_for_portfolio(
            pp,
            ranking_lookup,
            top5_lookup,
            take_profit_target=take_profit_target,
            min_buy_accuracy=min_acc,
            akurasi_pct=_acc_pct(p["ticker"])
        )
        d = _nudge_investasi(d, p["ticker"])
        if d and d["action"] == "SELL":
            # Tunda SELL demi DIVIDEN bila ex-date dekat & aman (bukan cut-loss/TP/AVOID dalam)
            rsn = d.get("reason", "")
            hard = ("CUT LOSS" in rsn or "TAKE PROFIT" in rsn or "AVOID" in rsn)
            defer = None
            try:
                prof = dividend.profile(p["ticker"], p.get("current_price"))
                defer = dividend.should_defer_sell(prof, pp["pnl"], hard)
            except Exception:  # noqa: BLE001
                defer = None
            if defer:
                d2 = {"ticker": p["ticker"], "action": "HOLD", "urgency": "LOW", "confidence": "MEDIUM",
                      "context": "HOLD_DIVIDEN",
                      "reason": (f"Tahan untuk DIVIDEN — ex-date ~{defer['ex_date']} ({defer['days_until']} hari, "
                                 f"~Rp {defer['amount']:.0f}/lembar ≈ {defer['event_yield_pct']}%). Sinyal jual semula: {rsn[:60]}"),
                      "next_step": "Jual SETELAH cum-date (ambil dividen). Catatan: harga biasanya turun ~sebesar dividen di ex-date.",
                      "details": {"broker": broker, "dividend": defer}}
                acc_val = _acc_pct(p["ticker"])
                acc_val = acc_val if acc_val is not None else 0.0
                sort_key = (acc_val, _conviction(ri, acc_cache.get(p["ticker"]))["conviction"])
                keepers_by_rdn.setdefault(broker, []).append((sort_key, pp, d2))
                continue
            d.setdefault("details", {})["broker"] = broker
            sell.append(d)                                  # eksit wajib → kosongkan slot RDN-nya
        else:
            # keeper diperingkat dgn SKOR KEYAKINAN GABUNGAN yang sama (konsisten dgn kandidat)
            acc_val = _acc_pct(p["ticker"])
            acc_val = acc_val if acc_val is not None else 0.0
            kc = _conviction(ri, acc_cache.get(p["ticker"]))["conviction"]
            sort_key = (acc_val, kc)
            keepers_by_rdn.setdefault(broker, []).append((sort_key, pp, d))

    # ---- 2. Kandidat BELI dari peringkat utama, urut SKOR KEYAKINAN GABUNGAN ---- #
    # (KONSISTEN dgn Top-5 & menyatukan funnel + undervalue + akurasi → semua AI dipakai)
    cands: list[tuple[float, dict, dict]] = []
    for _strength, s in prime:
        tk = s["ticker"]
        if tk in portfolio_set:
            continue
        cv = conv_map[tk]
        base = decide_for_watchlist(s, prospects_set, top5_lookup)
        base = _nudge_investasi(base, tk)
        if not base:
            continue
        rank = top5_lookup.get(tk)
        fs = s.get("fundamental_score") or 0
        reason = (base["reason"] if base else
                  f"Pilihan kuat — Fund {fs}/7 · {s.get('final_signal', '')}")
        acc = cv["akurasi_pct"]
        d = {"ticker": tk, "action": "BUY", "urgency": "HIGH",
             "confidence": "HIGH" if cv["conviction"] >= 55 else "MEDIUM",
             "context": "FILL_SLOT",
             "reason": (f"Top-{rank} pilihan · " if rank else "") + reason,
             "details": {"strength": cv["conviction"]}, "akurasi_pct": acc,
             "uv_score": cv["uv_score"], "funnel_skor": cv["funnel_skor"], "funnel_signal": cv["final_signal"],
             "conviction": cv["conviction"], "dividend_bonus": cv.get("dividend_bonus"),
             "expected_return_pct": (base or {}).get("expected_return_pct"),
             "next_step": (base or {}).get("next_step") or "Isi slot emiten (lihat alokasi)."}
        cands.append((cv["conviction"], s, d))
    # Urutkan berdasarkan prioritas tingkat akurasi trading (akurasi_pct), lalu conviction
    cands.sort(key=lambda x: (
        x[2].get("akurasi_pct") if x[2].get("akurasi_pct") is not None else 0.0,
        x[0]
    ), reverse=True)

    # ---- Saring kandidat berdasarkan ambang akurasi adaptif yang telah dihitung ---- #
    cands = [c for c in cands if (c[2].get("akurasi_pct") or 0) >= min_acc]      # saring per akurasi

    # ---- 3-7. Logika slot N-emiten DIJALANKAN PER RDN ---- #
    used_cand = set()
    strategi_rdn: list[dict] = []
    tot_kept = tot_fill = tot_trim = tot_rot = tot_open = 0
    for broker in sorted(set(keepers_by_rdn) | set(rdn_cash)):
        if broker == "Tring Pegadaian":
            continue
        has_cash = rdn_cash.get(broker, 0) > 0
        ks = sorted(keepers_by_rdn.get(broker, []), key=lambda x: x[0], reverse=True)
        kept = ks[:target]
        trimmed = ks[target:]

        # 3a. Pangkas kelebihan emiten di RDN ini
        for sort_key, p, _d in trimmed:
            pnl = p.get("pnl", 0) or 0
            _, strength = sort_key
            sell.append({
                "ticker": p["ticker"], "action": "SELL", "urgency": "HIGH", "confidence": "HIGH",
                "context": "PORTFOLIO_TRIM",
                "reason": f"[{broker}] Pangkas ke {target} emiten/RDN — emiten terlemah "
                          f"(skor {strength}, P/L {pnl:+.1f}%).",
                "details": {"pnl": pnl, "strength": strength, "broker": broker},
                "next_step": f"Jual untuk fokus {target} emiten terbaik di {broker}."})

        open_slots = max(0, target - len(kept))

        # 3b. Rotasi di RDN ini (slot penuh, ada cash, kandidat jauh lebih kuat)
        rotation = None
        if open_slots == 0 and kept and has_cash:
            best = next(((st, s, d) for st, s, d in cands if s["ticker"] not in used_cand), None)
            if best and best[0] - kept[-1][0][1] >= margin:       # bandingkan conviction vs conviction
                rotation = (kept[-1], best)
                kept = kept[:-1]
                used_cand.add(best[1]["ticker"])

        # 3c. Keputusan keeper yang dipertahankan
        for sort_key, p, d in kept:
            _, strength = sort_key
            if not d:
                d = {"ticker": p["ticker"], "action": "HOLD", "urgency": "LOW", "confidence": "MEDIUM",
                     "context": "PORTFOLIO_HOLD", "reason": f"P/L {p.get('pnl', 0):+.1f}% — pertahankan."}
            d.setdefault("details", {}).update({"strength": strength, "broker": broker})
            d["reason"] = f"[{broker} · jaga {target}] " + d["reason"]
            d["next_step"] = d.get("next_step") or f"Simpan (HOLD) {p['ticker']}."
            {"BUY": buy, "HOLD": hold, "SELL": sell}.get(d["action"], hold).append(d)

        # 3d. Isi slot kosong dgn BELI (HANYA bila RDN punya cash)
        fills = 0
        if open_slots > 0 and has_cash:
            for st, s, d in cands:
                if s["ticker"] in used_cand:
                     continue
                used_cand.add(s["ticker"])
                d["urgency"], d["context"] = "HIGH", "FILL_SLOT"
                d["reason"] = f"[{broker}] Isi slot ke-{len(kept) + fills + 1}/{target} — " + d["reason"]
                d["details"] = {**d.get("details", {}), "strength": st, "broker": broker}
                d["alokasi_rdn"] = broker
                buy.append(d)
                fills += 1
                if fills >= open_slots:
                    break

        # 3e. Terapkan rotasi (jual lemah + beli kuat) di RDN ini
        if rotation:
            (ws_key, wp, _), (c_key, cc, cd) = rotation
            ws = ws_key[1]
            cs = round(c_key, 1)                                # conviction kandidat
            sell.append({
                "ticker": wp["ticker"], "action": "SELL", "urgency": "HIGH", "confidence": "HIGH",
                "context": "ROTATION_OUT",
                "reason": f"[{broker}] Rotasi keluar — {cc['ticker']} (skor {cs}) jauh lebih kuat "
                          f"dari {wp['ticker']} (skor {ws}).",
                "details": {"strength": ws, "pnl": wp.get("pnl", 0), "broker": broker},
                "next_step": f"Jual {wp['ticker']} di {broker}, alihkan ke {cc['ticker']}."})
            cd["urgency"], cd["confidence"], cd["context"] = "HIGH", "HIGH", "ROTATION_IN"
            cd["reason"] = f"[{broker}] Rotasi masuk — lebih kuat dari {wp['ticker']} (skor {cs} vs {ws}). " + cd["reason"]
            cd["details"] = {**cd.get("details", {}), "strength": cs, "broker": broker}
            cd["alokasi_rdn"] = broker
            buy.append(cd)

        strategi_rdn.append({
            "broker": broker, "cash": round(rdn_cash.get(broker, 0)), "has_cash": has_cash,
            "dipertahankan": len(kept), "slot_kosong": open_slots, "akan_diisi": fills,
            "dipangkas": len(trimmed), "rotasi": bool(rotation),
            "perkiraan_setelah_aksi": len(kept) + fills + (1 if rotation else 0),
            "blokir_isi": open_slots > 0 and not has_cash,   # slot kosong tapi cash 0
        })
        tot_kept += len(kept)
        tot_fill += fills
        tot_trim += len(trimmed)
        tot_open += open_slots
        tot_rot += 1 if rotation else 0

    # ---- 8. Kandidat cadangan (info, bukan aksi) ---- #
    watch = [{"ticker": s["ticker"], "strength": round(st, 1), "akurasi_pct": d.get("akurasi_pct"),
              "reason": d["reason"], "context": d.get("context")}
             for st, s, d in cands if s["ticker"] not in used_cand][:5]

    # ---- 8b. Bursa tutup → sinyal teknikal & average-down ditahan jadi HOLD ---- #
    # (dilewati bila Mode Uji aktif: sistem berlaku seperti bursa buka)
    if bursa["closed"] and not test_mode:
        soft_sell, soft_buy = [], []
        for d in sell:
            r = d.get("reason", "")
            hard = ("CUT LOSS" in r or "TAKE PROFIT" in r or "AVOID" in r
                    or d.get("context") in ("PORTFOLIO_TRIM", "ROTATION_OUT"))
            if not hard and d["ticker"] in portfolio_set:      # sinyal teknikal → tahan
                hold.append({**d, "action": "HOLD", "urgency": "LOW", "confidence": "MEDIUM",
                             "context": "HOLD_BURSA_TUTUP",
                             "reason": "⏸ Bursa tutup — " + r + " (tahan, tinjau saat buka).",
                             "next_step": "Tahan; evaluasi ulang saat bursa buka."})
            else:
                d["next_step"] = "⏸ Rencanakan; eksekusi saat bursa buka. " + d.get("next_step", "")
                soft_sell.append(d)
        sell = soft_sell
        for d in buy:
            if d.get("context") in ("PORTFOLIO_AVG_DOWN", "PORTFOLIO_ADD"):
                hold.append({**d, "action": "HOLD", "urgency": "LOW", "confidence": "MEDIUM",
                             "context": "HOLD_BURSA_TUTUP",
                             "reason": "⏸ Bursa tutup — " + d.get("reason", "") + " (tahan).",
                             "next_step": "Tahan; tambah saat buka bila sinyal bertahan."})
            else:
                soft_buy.append(d)
        buy = soft_buy

    # ---- Rekomendasi Emas (Tring Pegadaian) ---- #
    try:
        # Tentukan tren pasar IHSG (UPTREND/DOWNTREND)
        market_trend = "UPTREND"
        try:
            idx_df = provider.get_index_history(period="2y")
            if idx_df is not None and not idx_df.empty and len(idx_df) >= 200:
                close_val = float(idx_df["Close"].iloc[-1])
                sma200_val = float(idx_df["Close"].rolling(200).mean().iloc[-1])
                market_trend = "UPTREND" if close_val > sma200_val else "DOWNTREND"
        except Exception:
            pass

        # Ambil data emas dari RDN breakdown
        gold_acc = None
        for item in brk.get("rdn", []):
            if item.get("broker") == "Tring Pegadaian":
                gold_acc = item
                break

        # Ambil harga emas per gram IDR
        from app.core import commodities
        gold_price_g = None
        for item in commodities.commodities().get("emas_komoditas", []):
            if "gram" in item.get("unit", ""):
                gold_price_g = item.get("harga")
                break

        if gold_acc and gold_price_g:
            gold_balance = gold_acc.get("gold_balance_grams") or 0.0
            gold_avg_price = gold_acc.get("gold_avg_price") or 0.0
            gold_cost = gold_acc.get("gold_cost") or 0.0

            # Spread Pegadaian adalah 3.5%
            spread = 0.035
            gold_price_sell = gold_price_g * (1.0 - spread)

            # Hitung net profit/loss setelah spread
            if gold_avg_price > 0:
                gold_pl_net_pct = round(((gold_price_sell - gold_avg_price) / gold_avg_price) * 100, 2)
            else:
                gold_pl_net_pct = 0.0

            gold_pl_gross_pct = gold_acc.get("gold_pl_pct") or 0.0

            # Logika keputusan emas
            if market_trend == "UPTREND":
                if gold_balance > 0:
                    if gold_pl_net_pct > 0:
                        # SELL
                        gold_rec = {
                            "ticker": "🪙 EMAS",
                            "action": "SELL",
                            "urgency": "HIGH",
                            "confidence": "HIGH",
                            "context": "GOLD_SELL_PROFIT",
                            "reason": f"Pasar saham bullish (IHSG Uptrend) & emas untung bersih {gold_pl_net_pct:+.2f}% setelah spread 3.5% (kotor {gold_pl_gross_pct:+.2f}%).",
                            "next_step": "Cairkan emas di Tring Pegadaian secara instan ke RDN Profits Anywhere untuk belanja saham syariah potensial.",
                            "expected_return_pct": gold_pl_net_pct,
                            "conviction": None,
                            "akurasi_pct": None,
                            "syariah_note": "Sesuai Fatwa DSN-MUI No. 77/2010 (Tunai & Taqabudh Hukmi)"
                        }
                        sell.append(gold_rec)
                    else:
                        # HOLD
                        gold_rec = {
                            "ticker": "🪙 EMAS",
                            "action": "HOLD",
                            "urgency": "LOW",
                            "confidence": "MEDIUM",
                            "context": "GOLD_HOLD_SPREAD",
                            "reason": f"Pasar saham bullish (IHSG Uptrend), namun menjual emas sekarang rugi bersih {gold_pl_net_pct:+.2f}% (kotor {gold_pl_gross_pct:+.2f}%) karena spread Pegadaian 3.5%.",
                            "next_step": "Tahan emas (HOLD) hingga kenaikan harga menutupi spread, kecuali butuh likuiditas mendesak.",
                            "expected_return_pct": None,
                            "conviction": None,
                            "akurasi_pct": None,
                            "syariah_note": "Sesuai Fatwa DSN-MUI No. 77/2010 (Tunai & Taqabudh Hukmi)"
                        }
                        hold.append(gold_rec)
                else:
                    # HOLD / Pantau (tidak ada aksi)
                    gold_rec = {
                        "ticker": "🪙 EMAS",
                        "action": "HOLD",
                        "urgency": "LOW",
                        "confidence": "LOW",
                        "context": "GOLD_HOLD_NO_BALANCE",
                        "reason": "Pasar saham sedang bullish (IHSG Uptrend) & tidak memiliki saldo emas.",
                        "next_step": "Prioritaskan dana RDN untuk membeli saham syariah pilihan di kolom BELI.",
                        "expected_return_pct": None,
                        "conviction": None,
                        "akurasi_pct": None,
                        "syariah_note": "Sesuai Fatwa DSN-MUI No. 77/2010 (Tunai & Taqabudh Hukmi)"
                    }
                    hold.append(gold_rec)
            else:  # DOWNTREND
                if gold_balance == 0:
                    # BUY
                    gold_rec = {
                        "ticker": "🪙 EMAS",
                        "action": "BUY",
                        "urgency": "HIGH",
                        "confidence": "HIGH",
                        "context": "GOLD_BUY_SAFE_HAVEN",
                        "reason": "Pasar saham bearish (IHSG Downtrend). Belum memiliki aset emas.",
                        "next_step": "Amankan Dana Cadangan (Reserve Fund) ke Emas Digital Tring Pegadaian sebagai safe-haven dari penurunan pasar saham.",
                        "expected_return_pct": None,
                        "conviction": None,
                        "akurasi_pct": None,
                        "syariah_note": "Sesuai Fatwa DSN-MUI No. 77/2010 (Tunai & Taqabudh Hukmi)"
                    }
                    buy.append(gold_rec)
                else:
                    # HOLD
                    gold_rec = {
                        "ticker": "🪙 EMAS",
                        "action": "HOLD",
                        "urgency": "MEDIUM",
                        "confidence": "HIGH",
                        "context": "GOLD_HOLD_SAFE_HAVEN",
                        "reason": f"Pasar saham bearish (IHSG Downtrend). Emas berfungsi sebagai safe-haven pelindung nilai (Net P/L {gold_pl_net_pct:+.2f}%, kotor {gold_pl_gross_pct:+.2f}%).",
                        "next_step": "Pertahankan kepemilikan emas (HOLD) selama tren pasar saham masih lesu.",
                        "expected_return_pct": None,
                        "conviction": None,
                        "akurasi_pct": None,
                        "syariah_note": "Sesuai Fatwa DSN-MUI No. 77/2010 (Tunai & Taqabudh Hukmi)"
                    }
                    hold.append(gold_rec)
    except Exception as e:
        print(f"Error calculating gold decisions: {e}")

    # ---- 9. Pengayaan: akurasi prediksi + alokasi Money Management (sinkron MM/RDN) ---- #
    pos_by_tk = {p["ticker"]: p for p in positions}
    for lst in (buy, hold, sell):
        _enrich(lst, pos_by_tk, brk["rdn"], acc_cache)

    # BELI diurutkan berdasarkan prioritas tingkat akurasi trading (akurasi_pct), lalu conviction
    buy.sort(key=lambda d: (
        d.get("akurasi_pct") if d.get("akurasi_pct") is not None else 0.0,
        d.get("conviction") if d.get("conviction") is not None else 0.0,
        _URG.get(d["urgency"], 0)
    ), reverse=True)
    sell.sort(key=lambda d: (_URG.get(d["urgency"], 0), _CONF.get(d["confidence"], 0), d.get("akurasi_pct") or 0), reverse=True)
    hold.sort(key=lambda d: (d.get("akurasi_pct") or 0), reverse=True)

    buy_tk = {d["ticker"] for d in buy}
    hold_tk = {d["ticker"] for d in hold}
    sell_tk = {d["ticker"] for d in sell}

    def _status(tk: str) -> str:
        if tk in buy_tk:
            return "BELI"
        if tk in sell_tk:
            return "JUAL"
        if tk in hold_tk:
            return "HOLD"
        if tk in portfolio_set:
            return "DIMILIKI"
        return "TERTAHAN"          # kandidat kuat tapi belum dibeli (cash/slot/ambang akurasi)

    top5_detail = []
    for _strv, s in prime[:5]:
        tk = s["ticker"]
        cv = conv_map[tk]
        top5_detail.append({
            "ticker": tk, "akurasi_pct": cv["akurasi_pct"], "uv_score": cv["uv_score"],
            "funnel_skor": cv["funnel_skor"], "funnel_signal": cv["final_signal"],
            "conviction": cv["conviction"], "dividend_bonus": cv.get("dividend_bonus"),
            "owned": tk in portfolio_set, "status": _status(tk)})
    prioritized_tickers = [
        {"ticker": s["ticker"], "akurasi_pct": conv_map[s["ticker"]]["akurasi_pct"]}
        for _, s in prime
    ]
    
    # Hitung timing eksekusi harian/jam bursa untuk rekomendasi
    timing_str = _calculate_timing(bursa, test_mode)
    for lst in (buy, hold, sell, watch):
        for item in lst:
            item["execution_timing"] = timing_str
            
    return {
        "buy": buy, "hold": hold, "sell": sell, "watch": watch,
        "top5": top5, "top5_detail": top5_detail, "prospects": sorted(prospects_set), "bursa": bursa,
        "jumlah_ranking": len(ranking),
        "money_management": brk["total"], "rdn": brk["rdn"],
        "roi": roi.portfolio_roi(float(MM.PROFIT_FUND_PCT)), "adaptive": adaptive,
        "strategi": {
            "mode": "per_rdn",
            "target_emiten": target,
            "dimiliki_awal": len(positions),
            "dipertahankan": tot_kept,
            "slot_kosong": tot_open,
            "akan_diisi": tot_fill,
            "dipangkas": tot_trim,
            "rotasi": tot_rot,
            "perkiraan_setelah_aksi": tot_kept + tot_fill + tot_rot,
            "per_rdn": strategi_rdn,
        },
        "jumlah": {"buy": len(buy), "hold": len(hold), "sell": len(sell)},
        "prioritized_tickers": prioritized_tickers,
    }


def _calculate_timing(bursa: dict, test_mode: bool = False) -> str:
    """Hitung timing eksekusi dalam satuan jam & hari."""
    from datetime import datetime, time as _time, timedelta
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Jakarta"))
    except Exception:
        now = datetime.now()
        
    if test_mode or bursa.get("open"):
        # Bursa sedang buka -> hitung jam tersisa hingga penutupan sesi-2 (16:00 WIB)
        try:
            tutup = datetime.combine(now.date(), _time(16, 0))
            if now.tzinfo is not None:
                tutup = tutup.replace(tzinfo=now.tzinfo)
            if now < tutup:
                diff = tutup - now
                seconds = diff.total_seconds()
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                if hours > 0:
                    return f"{hours} jam {minutes} menit (sebelum bursa tutup hari ini)"
                else:
                    return f"{minutes} menit (sebelum bursa tutup hari ini)"
        except Exception:
            pass
        return "5 jam (selama jam perdagangan harian)"
    else:
        # Bursa tutup -> hitung waktu menuju pembukaan bursa berikutnya (Senin-Jumat, 09:00 WIB)
        try:
            next_trading_day = now.date()
            while True:
                # Jika hari ini bursa tutup dan sekarang sebelum jam 9, target hari ini pukul 09:00 WIB
                if next_trading_day == now.date() and now.time() < _time(9, 0) and not bursa.get("weekend") and not bursa.get("holiday"):
                    break
                next_trading_day += timedelta(days=1)
                if next_trading_day.weekday() >= 5:
                    continue
                if bei_calendar.is_holiday(next_trading_day):
                    continue
                break
                
            buka_target = datetime.combine(next_trading_day, _time(9, 0))
            if now.tzinfo is not None:
                buka_target = buka_target.replace(tzinfo=now.tzinfo)
                
            diff = buka_target - now
            days = diff.days
            seconds = diff.seconds
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            
            parts = []
            if days > 0:
                parts.append(f"{days} hari")
            if hours > 0:
                parts.append(f"{hours} jam")
            if minutes > 0 and days == 0:
                parts.append(f"{minutes} menit")
                
            if not parts:
                return "Segera saat bursa buka"
            return " ".join(parts) + " (menunggu bursa buka)"
        except Exception:
            pass
        return "1 hari (saat pembukaan bursa berikutnya)"
