"""
Advisor Lokal (GRATIS) — narasi analisa berbasis aturan, tanpa API/biaya.

Menyusun penjelasan bahasa Indonesia dari hasil funnel (syariah + 6 Magic +
CAN SLIM + teknikal), meniru struktur AI Advisor tapi 100% deterministik dan
offline. Dipakai sebagai fallback bila ANTHROPIC_API_KEY tidak di-set.
"""

from __future__ import annotations

from typing import Any

from app.core import trading_plan


def _fmt(n: Any) -> str:
    try:
        return f"{float(n):,.0f}".replace(",", ".")
    except Exception:
        return str(n)


def advise(report: dict[str, Any]) -> dict[str, Any]:
    sh = report.get("sharia", {})
    f = report.get("fundamental", {})
    c = report.get("canslim", {})
    t = report.get("technical", {})
    rec = report.get("rekomendasi", {})
    tk = report.get("ticker", "")
    name = report.get("name") or ""

    p: list[str] = []

    # 1. Ringkasan & syariah
    if not sh.get("compliant"):
        p.append(f"❌ {tk} TIDAK lolos screening syariah (di luar DES/ISSI). "
                 "Sesuai Fatwa DSN-MUI, saham ini dilewati — tidak ada saran trading.")
        return {"enabled": True, "model": "Analisa Lokal (gratis)", "analisa": "\n\n".join(p)}

    p.append(f"📌 RINGKASAN — {tk} {('('+name+')') if name else ''}\n"
             f"Lolos screening syariah (DES/ISSI). Skor funnel {rec.get('skor','-')}/100 · "
             f"Rekomendasi mesin: {rec.get('aksi','-')}.")

    # 2. Kekuatan
    kuat: list[str] = []
    for cr in f.get("checks", []):
        if cr.get("lolos"):
            kuat.append(f"{cr['kriteria']} {cr['nilai']} (target {cr['target']})")
    if f.get("bonus_dividend", {}).get("lolos"):
        kuat.append(f"Dividend Yield {f['bonus_dividend']['nilai']}")
    cs_pass = [f"{k} ({v['nilai']})" for k, v in c.get("letters", {}).items() if v.get("lolos")]
    if cs_pass:
        kuat.append("CAN SLIM lolos: " + ", ".join(cs_pass))
    if t.get("ok") and t.get("trend") == "UPTREND":
        kuat.append("tren teknikal UPTREND (harga di atas SMA200)")
    p.append("✅ KEKUATAN\n" + ("\n".join("• " + s for s in kuat) if kuat else "• Terbatas — lihat catatan risiko."))

    # 3. Kelemahan / risiko
    lemah: list[str] = []
    for cr in f.get("checks", []):
        if cr.get("lolos") is False:
            lemah.append(f"{cr['kriteria']} {cr['nilai']} belum penuhi target {cr['target']}")
        elif cr.get("lolos") is None:
            lemah.append(f"{cr['kriteria']}: data tidak tersedia")
    cs_fail = [k for k, v in c.get("letters", {}).items() if v.get("lolos") is False]
    if cs_fail:
        lemah.append("CAN SLIM belum penuhi: " + ", ".join(cs_fail))
    if t.get("ok") and t.get("trend") == "DOWNTREND":
        lemah.append("tren DOWNTREND — risiko 'pisau jatuh', sebaiknya tunggu pembalikan")
    if t.get("ok"):
        liq = t.get("liquidity_risk", "Rendah")
        if liq == "Sangat Tinggi":
            lemah.append("risiko likuiditas SANGAT TINGGI (saham tidak likuid) — rawan jebakan Fake Bid/Offer (antrean palsu), spread lebar, & sulit exit posisi")
            lemah.append("peringatan order book: jangan jadikan antrean bid/offer sebagai satu-satunya acuan (rawan manipulasi pre-closing / BSJP)")
        elif liq == "Sedang":
            lemah.append("risiko likuiditas SEDANG — waspadai antrean bid/offer palsu & perubahan ekstrem menjelang penutupan (pre-closing)")
    p.append("⚠️ RISIKO / CATATAN\n" + ("\n".join("• " + s for s in lemah) if lemah else "• Tidak ada catatan signifikan."))

    # 4. Teknikal & timing
    if t.get("ok"):
        st = t.get("stochastic", {})
        tl = [f"Tren {t.get('trend')} · {t.get('bias')}",
              f"Stochastic %K {st.get('k')} ({st.get('zona')}) · {st.get('sinyal')}",
              f"Support {_fmt(t.get('support'))} · Resistance {_fmt(t.get('resistance'))}"]
        sigs = t.get("entry_signals", [])
        if sigs:
            tl.append("Sinyal entry: " + ", ".join(f"{s['kode']} ({s['nama']})" for s in sigs))
        if t.get("candlestick"):
            tl.append("Pola candle: " + ", ".join(t["candlestick"]))
        p.append("📈 TEKNIKAL & TIMING\n" + "\n".join("• " + s for s in tl))
    else:
        p.append("📈 TEKNIKAL & TIMING\n• Data harga tidak cukup untuk analisa teknikal.")

    # 5. Saran trading plan
    p.append(_plan_suggestion(rec, t))

    # 6. Disclaimer
    p.append("ℹ️ Analisa otomatis berbasis aturan modul — BUKAN ajakan jual/beli. "
             "Keputusan & risiko di tangan Anda. Transaksi tunai (non-margin), sesuai syariah.")

    return {"enabled": True, "model": "Analisa Lokal (gratis · tanpa API)", "analisa": "\n\n".join(p)}


def _plan_suggestion(rec: dict[str, Any], t: dict[str, Any]) -> str:
    css = rec.get("css", "")
    if not t.get("ok"):
        return "🎯 SARAN\n• Data teknikal belum cukup untuk menyusun rencana entry."
    price = t.get("price")
    support = t.get("support")
    resistance = t.get("resistance")

    if css == "buy" and price and support and support < price:
        cl = support
        rr = trading_plan.risk_reward(price, cl, take_profit=None, target_reward_mult=2)
        tp = rr.get("take_profit")
        line = (f"Kandidat entry di sekitar {_fmt(price)}. "
                f"Pasang cut loss di area support {_fmt(cl)}, "
                f"target profit ±{_fmt(tp)} (RRR {rr.get('rrr')}). ")
        if resistance and resistance > price:
            line += f"Resistance terdekat {_fmt(resistance)} — pantau breakout dengan volume. "
        line += "Gunakan position sizing (LOT = Modal ÷ harga ÷ 100) & hanya uang dingin."
        return "🎯 SARAN TRADING PLAN\n• " + line
    if css == "warning":
        return ("🎯 SARAN\n• Akumulasi bertahap (fundamental baik, teknikal belum BUY) — cicil di "
                "watchlist, tunggu konfirmasi golden cross / breakout dengan volume.")
    if t.get("trend") == "DOWNTREND":
        return ("🎯 SARAN\n• Hindari entry saat tren turun. Tunggu harga kembali di atas SMA200 "
                "atau muncul pola pembalikan (reversal) sebelum mempertimbangkan posisi.")
    return ("🎯 SARAN\n• Belum layak entry. Perbaiki dulu pemenuhan kriteria fundamental/teknikal, "
            "atau alihkan ke saham syariah lain dengan skor lebih tinggi.")
