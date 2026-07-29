"""
Narator sinyal — pesan Telegram kedua per sesi: penjelasan & pembelajaran
atas 3 saham teratas.

Prinsip (sesuai brief proyek): penjelasan DITURUNKAN dari fitur nyata yang
dilihat model (top_features hasil predict()) — tidak pernah mengarang angka.
Setiap saham mendapat: narasi apa-yang-dilihat-model, catatan aturan/risiko,
dan satu "📚 Pelajaran" yang dipilih dari fitur paling berpengaruh.
"""

from __future__ import annotations

from typing import Any, Optional


def _fmt_rp(v: Any) -> str:
    try:
        return f"{float(v):,.0f}".replace(",", ".")
    except Exception:
        return "—"


def _feat_sentence(name: str, val: Optional[float]) -> Optional[str]:
    """Terjemahkan (fitur, nilai) menjadi kalimat Indonesia. None = lewati."""
    if val is None:
        return None
    p = val * 100
    if name == "close_sma200":
        arah = "di atas" if val > 0 else "di bawah"
        return f"harga {abs(p):.0f}% {arah} rata-rata 200 hari ({'tren panjang sehat' if val > 0 else 'tren panjang masih tertekan'})"
    if name == "sma50_sma200":
        return ("rata-rata 50 hari di atas 200 hari (formasi golden — momentum jangka menengah positif)"
                if val > 0 else "rata-rata 50 hari masih di bawah 200 hari (momentum menengah belum pulih)")
    if name == "dist_high52w":
        return f"berjarak {abs(p):.0f}% dari puncak 52 minggu ({'dekat breakout' if abs(p) < 10 else 'ruang pemulihan masih lebar'})"
    if name == "dist_low52w":
        return f"sudah naik {p:.0f}% dari titik terendah 52 minggu"
    if name == "rsi14":
        zona = "oversold — pantulan mungkin" if val < 30 else ("overbought — hati-hati kejar harga" if val > 70 else "zona netral")
        return f"RSI {val:.0f} ({zona})"
    if name == "ret_20":
        return f"return 20 hari terakhir {p:+.0f}%"
    if name == "ret_60":
        return f"return 60 hari terakhir {p:+.0f}%"
    if name in ("rs_20", "rs_60"):
        h = name.split("_")[1]
        return (f"mengungguli IHSG {p:+.0f}% dalam {h} hari (relative strength positif)"
                if val > 0 else f"tertinggal {abs(p):.0f}% dari IHSG dalam {h} hari")
    if name == "vol_ratio20":
        return (f"volume {val:.1f}× rata-rata 20 hari (minat pasar meningkat)"
                if val > 1.3 else f"volume {val:.1f}× rata-rata (aktivitas normal)")
    if name == "atr14_pct":
        return f"volatilitas harian ±{p:.1f}% (ATR) — {'liar, size kecil' if p > 4 else 'terkendali'}"
    if name == "std20":
        return f"simpangan harian 20 hari {p:.1f}%"
    if name == "mkt_close_sma200":
        return (f"konteks pasar: IHSG {abs(p):.0f}% {'di atas' if val > 0 else 'di bawah'} SMA200-nya")
    if name == "mkt_ret_20":
        return f"IHSG bergerak {p:+.1f}% dalam 20 hari terakhir"
    if name == "breakout20":
        return "baru menembus harga tertinggi 20 hari (breakout)" if val > 0 else None
    if name == "breakout60":
        return "baru menembus harga tertinggi 60 hari (breakout besar)" if val > 0 else None
    if name == "month":
        return None                       # musiman — kurang edukatif utk narasi
    return None


_PELAJARAN = {
    "close_sma200": "SMA200 adalah 'garis hidup' tren: di atasnya, koreksi cenderung pantulan; di bawahnya, pantulan cenderung jebakan. Komponen M pada CAN SLIM.",
    "sma50_sma200": "Golden cross (MA50 memotong MA200 ke atas) menandai perubahan rezim tren — sinyal lambat tapi jarang berbohong; kebalikannya death cross.",
    "dist_high52w": "Saham yang mendekati puncak 52-minggunya justru sering melanjutkan naik (huruf N pada CAN SLIM: New High) — puncak lama = area tanpa penjual nyangkut.",
    "dist_low52w": "Jarak dari titik terendah mengukur seberapa jauh pemulihan berjalan; pemulihan tahap awal berisiko-tinggi berimbal-tinggi.",
    "rsi14": "RSI mengukur kecepatan naik-turun, bukan arah: <30 jenuh jual, >70 jenuh beli. Paling berguna saat berlawanan dengan gerak harga (divergensi).",
    "rs_60": "Relative strength vs indeks adalah saringan O'Neil: belilah yang memimpin pasar, bukan yang tertinggal — pemimpin cenderung terus memimpin.",
    "rs_20": "Relative strength jangka pendek menangkap rotasi sektor lebih dini daripada harga absolut.",
    "vol_ratio20": "Volume adalah bahan bakar harga: kenaikan tanpa volume mudah layu; lonjakan volume + harga naik = akumulasi institusi.",
    "atr14_pct": "ATR menentukan ukuran posisi: makin liar sahamnya, makin kecil porsi modalnya — supaya stop-loss 7% tidak tersentuh oleh noise harian.",
    "mkt_close_sma200": "Serapi apa pun sahamnya, 3 dari 4 saham bergerak searah pasar — itulah kenapa regime IHSG memotong ukuran posisi di sistem ini.",
    "mkt_ret_20": "Momentum indeks 20 hari adalah 'cuaca' trading: melawan cuaca boleh, tapi bawa payung (size kecil, stop ketat).",
    "std20": "Volatilitas historis membantu membedakan pergerakan berarti dari noise: gerakan < 1 simpangan harian belum tentu sinyal.",
}


def _narasi_satu(tk: str, name: str, price: Any, pr: dict[str, Any],
                 rule_signal: Optional[str]) -> list[str]:
    p_buy = float(pr.get("p_buy") or 0)
    p_sell = float(pr.get("p_sell") or 0)
    feats = pr.get("top_features") or []
    kalimat = []
    for f in feats[:5]:
        s = _feat_sentence(f.get("feature"), f.get("value"))
        if s:
            kalimat.append(s)
        if len(kalimat) >= 3:
            break
    lines = [f"<b>{tk}</b>{(' — ' + name) if name else ''} · Rp{_fmt_rp(price)} · "
             f"P(BUY) {p_buy:.0%} / P(SELL) {p_sell:.0%}"]
    if kalimat:
        lines.append("Yang dilihat model: " + "; ".join(kalimat) + ".")
    if rule_signal:
        setuju = rule_signal in ("STRONG BUY", "BUY", "SPECULATIVE BUY", "ACCUMULATE")
        lines.append("Mesin konvensional: " + (
            f"<b>{rule_signal}</b> — sejalan." if setuju else
            f"<b>{rule_signal}</b> — berbeda pendapat (biasanya karena disiplin "
            f"regime pasar); track record yang mengadili."))
    # Pelajaran: dari fitur ter-penting yang punya materi
    for f in feats:
        les = _PELAJARAN.get(f.get("feature") or "")
        if les:
            lines.append(f"📚 <i>Pelajaran:</i> {les}")
            break
    return lines


def build_narrative(picks: list[dict[str, Any]], label: Optional[str],
                    predict_fn=None) -> Optional[str]:
    """Pesan narasi utk <=3 pilihan teratas. None bila tidak ada bahan.

    picks: [{ticker, name, price, rule_signal}] — probabilitas & fitur
    diambil segar via predict() agar penjelasan setia pada model.
    """
    if not picks:
        return None
    if predict_fn is None:
        from app.core.ml_signal import predict as predict_fn  # type: ignore
    blok: list[str] = []
    for pk in picks[:3]:
        tk = pk.get("ticker") or ""
        try:
            pr = predict_fn(tk)
        except Exception:
            continue
        if not pr.get("available"):
            continue
        blok.append("\n".join(_narasi_satu(tk, pk.get("name") or "",
                                           pk.get("price"), pr,
                                           pk.get("rule_signal"))))
    if not blok:
        return None
    head = f"🎓 <b>Narasi & Pembelajaran</b> — 3 pilihan teratas"
    if label:
        head += f" · {label}"
    tail = ("<i>Penjelasan diturunkan dari fitur yang benar-benar dilihat model "
            "(bukan opini). Shadow mode — bukan perintah beli.</i>")
    return "\n\n".join([head] + blok + [tail])
