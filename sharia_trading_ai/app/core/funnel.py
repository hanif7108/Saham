"""
Stock Funnel (modul hal. 57) — orkestrasi end-to-end.

  700+ saham BEI
    -> 500+ saham Syariah        (sharia_screening)        WHAT to buy
    -> screening CAN SLIM        (canslim + fundamental)   WHY to buy
    -> analisa teknikal          (technical)               WHEN to buy
    -> money management & plan    (trading_plan)            HOW to trade

"Trade What You Plan & Plan What You Trade."
"""

from __future__ import annotations

from typing import Any, Optional

from app.core import bandarmologi, canslim, fundamental, jalur7, sharia_screening, technical
from app.data import provider


def analyze_stock(ticker: str) -> dict[str, Any]:
    """Laporan lengkap satu saham melewati seluruh funnel."""
    ticker = ticker.upper()
    info = provider.get_info(ticker)
    hist = provider.get_history(ticker)
    index_hist = provider.get_index_history()

    sharia = sharia_screening.screen_sharia(ticker, info=info)
    fund = fundamental.evaluate_fundamental(ticker, info=info)
    cslim = canslim.evaluate_canslim(ticker, info=info, hist=hist, index_hist=index_hist)
    tech = technical.analyze_technical(ticker, hist=hist)
    osignal = technical.oneill_signal(hist, ticker)
    j7 = jalur7.evaluate_jalur7(ticker, hist=hist)
    bandar = bandarmologi.get_bandar_analysis(ticker, hist=hist)

    recommendation = _recommend(sharia, fund, cslim, tech, j7, osignal, bandar)

    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName"),
        "sector": provider.sector_of(ticker) or info.get("sector"),
        "sharia": sharia,
        "fundamental": fund,
        "canslim": cslim,
        "technical": tech,
        "signal": osignal,
        "jalur7": j7,
        "bandarmologi": bandar,
        "rekomendasi": recommendation,
    }


def combine_signals(f_label: str, t_signal: str) -> tuple[str, str]:
    """final_signal ala app lama (scoring.combine_signals): fundamental_label × technical_signal."""
    if f_label == "AVOID":
        return "AVOID", "sell"
    if f_label == "STRONG BUY" and t_signal == "BUY":
        return "STRONG BUY", "buy"
    if f_label in ("STRONG BUY", "BUY") and t_signal == "BUY":
        return "BUY", "buy"
    if f_label in ("STRONG BUY", "BUY"):
        return "ACCUMULATE", "warning"
    if f_label == "HOLD" and t_signal == "BUY":
        return "SPECULATIVE BUY", "warning"
    if t_signal == "SELL":
        return "WATCH (Tech Weak)", "warning"
    return "HOLD", "hold"


def _recommend(sharia, fund, cslim, tech, j7=None, osignal=None, bandar=None) -> dict[str, Any]:
    if not sharia["compliant"]:
        return {"aksi": "AVOID (non-syariah)", "final_signal": "AVOID", "css": "sell",
                "alasan": ["Tidak lolos screening syariah (DES/ISSI)"], "skor": 0}

    magic = fund["magic_score"]
    cs = cslim["canslim_score"]
    f_label = fund.get("fundamental_label", "NO DATA")
    t_signal = (osignal or {}).get("signal") or ("BUY" if (tech.get("ok") and "BULLISH" in tech.get("bias", "")) else "HOLD")
    final, css = combine_signals(f_label, t_signal)
    
    # Gerbang Penyaring Akhir Bandarmologi: turunkan rekomendasi beli ke HOLD bila terdeteksi distribusi
    if bandar and not bandar.get("layak_beli", True) and final in ("BUY", "STRONG BUY", "SPECULATIVE BUY"):
        final = "HOLD (Dist. Bandar)"
        css = "hold"

    j7_score = j7["score"] if (j7 and j7.get("ok")) else None

    reasons = [
        f"Fundamental: {f_label} (6 Magic {magic}/6, skor penuh {fund.get('fund_full_score', magic)})",
        f"CAN SLIM: {cs}/7 ({cslim['verdict']})",
        f"Teknikal: sinyal {t_signal}" + (
            f" · MA {osignal['ma_cross']} · RSI {osignal['rsi']}" if osignal and osignal.get("ma_cross") else ""),
    ]
    if j7_score is not None:
        reasons.append(f"Jalur 7%: {j7_score}/4 ({j7['verdict']})")
    if bandar:
        reasons.append(f"Bandarmologi: {bandar['sentiment']} (skor {bandar['score']}/100) — {bandar['note']}")
    if tech and "fibonacci" in tech:
        fib = tech["fibonacci"]
        closest_note = fib.get("closest_level_note", "")
        next_cycle = None
        for cyc in fib.get("time_cycles", []):
            if cyc.get("days_left") is not None and cyc["days_left"] >= 0:
                if next_cycle is None or cyc["days_left"] < next_cycle["days_left"]:
                    next_cycle = cyc
        fib_reason = f"Fibonacci: {closest_note}"
        if next_cycle:
            days_left = next_cycle["days_left"]
            days_str = "hari ini" if days_left == 0 else f"{days_left} hari bursa lagi"
            fib_reason += f" · Proyeksi Reversal {next_cycle['date']} ({days_str})"
        reasons.append(fib_reason)

    # Cross-check independen: rekomendasi teknikal TradingView live (bila aktif).
    # Tidak menurunkan sinyal secara otomatis (advisory) — hanya menandai kontradiksi
    # agar timing beli yang berisiko terlihat jelas (kurangi false positive).
    tv = fund.get("tradingview")
    tv_cross = None
    if tv and tv.get("recommend_label"):
        lbl = tv["recommend_label"]
        rec_all = tv.get("recommend_all")
        buyish = final in ("STRONG BUY", "BUY", "SPECULATIVE BUY", "ACCUMULATE")
        contradiction = buyish and lbl in ("SELL", "STRONG SELL")
        tv_cross = {"recommend_label": lbl, "recommend_all": rec_all, "contradiction": contradiction}
        rec_str = f"{rec_all:.2f}" if isinstance(rec_all, (int, float)) else "n/a"
        if contradiction:
            reasons.append(
                f"⚠️ Cross-check TradingView: teknikal {lbl} (Recommend.All {rec_str}) "
                f"— timing beli berisiko, pertimbangkan menunggu konfirmasi."
            )
        else:
            reasons.append(f"Cross-check TradingView: teknikal {lbl} (Recommend.All {rec_str})")

    tech_pos = 1 if t_signal == "BUY" else 0
    j7_norm = (j7_score / 4) if j7_score is not None else 0
    skor = round((magic / 6 * 0.35 + cs / 7 * 0.35 + tech_pos * 0.15 + j7_norm * 0.15) * 100)
    return {"aksi": final, "final_signal": final, "css": css, "alasan": reasons,
            "skor": skor, "tv_cross_check": tv_cross}


def screen_universe(
    tickers: Optional[list[str]] = None,
    min_magic: int = 0,
    min_canslim: int = 0,
    require_uptrend: bool = False,
    limit: Optional[int] = None,
    potensi: Optional[str] = None,
    stoch_rsi_range: Optional[str] = None,
    golden_cross: Optional[str] = None,
) -> dict[str, Any]:
    """Jalankan funnel ke seluruh universe syariah, kembalikan hasil ter-ranking."""
    tickers = tickers or provider.universe_tickers()
    if limit:
        tickers = tickers[:limit]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    from concurrent.futures import ThreadPoolExecutor

    # Pra-muat data indeks IHSG sekali agar tidak terjadi file lock saat menulis cache secara paralel
    provider.get_index_history()

    # Pra-muat fundamental TradingView dalam SATU batch (cache TTL) bila sumber data
    # memakainya — supaya 75 worker membaca cache, bukan 75 request HTTP terpisah.
    from app.config import settings as _settings
    if (_settings.data_source or "").lower() in ("tradingview", "hybrid"):
        try:
            from app.data import tradingview_provider
            tradingview_provider.scan_fundamentals(tickers)
        except Exception:  # noqa: BLE001
            pass

    def process_ticker(t):
        try:
            info = provider.get_info(t)
            # Screen sharia terlebih dahulu demi efisiensi resource sebelum yfinance dipicu
            sh = sharia_screening.screen_sharia(t, info=info)
            if not sh["compliant"]:
                return None, None

            hist = provider.get_history(t)
            index_hist = provider.get_index_history()

            fund = fundamental.evaluate_fundamental(t, info=info)
            cslim = canslim.evaluate_canslim(t, info=info, hist=hist, index_hist=index_hist)
            tech = technical.analyze_technical(t, hist=hist)
            osignal = technical.oneill_signal(hist, t)
            j7 = jalur7.evaluate_jalur7(t, hist=hist)
            bandar = bandarmologi.get_bandar_analysis(t, hist=hist)

            if fund["magic_score"] < min_magic:
                return None, None
            if cslim["canslim_score"] < min_canslim:
                return None, None
            if require_uptrend and tech.get("trend") != "UPTREND":
                return None, None

            rec = _recommend(sh, fund, cslim, tech, j7, osignal, bandar)

            # Filter Potensi Naik / Turun
            if potensi == "naik":
                is_bullish = (
                    tech.get("trend") == "UPTREND" or
                    rec["final_signal"] in ("STRONG BUY", "BUY", "SPECULATIVE BUY", "ACCUMULATE") or
                    "BULLISH" in tech.get("bias", "")
                )
                if not is_bullish:
                    return None, None
            elif potensi == "turun":
                is_bearish = (
                    tech.get("trend") == "DOWNTREND" or
                    rec["final_signal"] in ("AVOID", "WATCH (Tech Weak)") or
                    "BEARISH" in tech.get("bias", "")
                )
                if not is_bearish:
                    return None, None

            # Filter Golden Cross
            stoch_gc = tech.get("stochastic", {}).get("sinyal", "").startswith("golden")
            ma_gc = osignal.get("ma_cross") == "GOLDEN"
            if golden_cross == "stoch":
                if not stoch_gc:
                    return None, None
            elif golden_cross == "ma":
                if not ma_gc:
                    return None, None
            elif golden_cross == "keduanya":
                if not (stoch_gc and ma_gc):
                    return None, None

            # Filter Stochastic RSI Range
            if stoch_rsi_range and stoch_rsi_range != "abaikan":
                k_val = tech.get("stochastic", {}).get("k")
                if k_val is None:
                    return None, None
                try:
                    low_b, high_b = map(float, stoch_rsi_range.split("-"))
                    if not (low_b <= k_val <= high_b):
                        return None, None
                except ValueError:
                    pass

            res = {
                "ticker": t,
                "name": info.get("longName") or info.get("shortName"),
                "sector": provider.sector_of(t),
                "magic_score": fund["magic_score"],
                "fundamental_label": fund.get("fundamental_label"),
                "canslim_score": cslim["canslim_score"],
                "jalur7_score": j7["score"] if j7.get("ok") else None,
                "bandarmologi": bandar,
                "technical_signal": osignal.get("signal"),
                "trend": tech.get("trend"),
                "price": tech.get("price"),
                "entry_signals": [s["kode"] for s in tech.get("entry_signals", [])],
                "stoch_k": tech.get("stochastic", {}).get("k"),
                "stoch_d": tech.get("stochastic", {}).get("d"),
                "stoch_sinyal": tech.get("stochastic", {}).get("sinyal"),
                "ma_cross": osignal.get("ma_cross"),
                "aksi": rec["aksi"],
                "final_signal": rec["final_signal"],
                "css": rec["css"],
                "skor": rec["skor"],
                "tv_cross_check": rec.get("tv_cross_check"),
            }
            return res, None
        except Exception as e:
            return None, {"ticker": t, "error": str(e)}

    # Pemuatan paralel 10 pekerja
    with ThreadPoolExecutor(max_workers=10) as executor:
        items = list(executor.map(process_ticker, tickers))

    for res, err in items:
        if res:
            results.append(res)
        if err:
            errors.append(err)

    results.sort(key=lambda r: r["skor"], reverse=True)
    return {
        "kriteria": {
            "min_magic": min_magic,
            "min_canslim": min_canslim,
            "require_uptrend": require_uptrend,
            "potensi": potensi,
            "stoch_rsi_range": stoch_rsi_range,
            "golden_cross": golden_cross,
        },
        "jumlah_universe": len(tickers),
        "jumlah_lolos": len(results),
        "hasil": results,
        "errors": errors,
    }
