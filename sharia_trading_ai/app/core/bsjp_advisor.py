"""
BSJP Advisor — Gemini (free tier) bila tersedia, fallback ke analisa berbasis aturan.

Fokus:
  - Analisa risiko overnight (gap down, likuiditas)
  - Estimasi IEP vs CP untuk keputusan jual pagi
  - Warning khusus saham berlikuiditas rendah
  - Rekomendasi konkret: entry/exit spesifik BSJP
"""

from __future__ import annotations

from typing import Any


def is_enabled() -> bool:
    return True


def advise_bsjp(ticker: str, candidate: dict[str, Any]) -> dict[str, Any]:
    """Gemini dulu (jika key ada); gagal/kuota → lokal berbasis aturan."""
    from app.core import gemini_advisor

    if gemini_advisor.is_enabled():
        result = gemini_advisor.advise_bsjp(ticker, candidate)
        if result.get("enabled") and not result.get("error") and result.get("analisa"):
            return result
        # fallback lokal, catat alasan
        local = _advise_local(ticker, candidate)
        err = result.get("error") or result.get("message") or "Gemini gagal"
        local["fallback_dari"] = "gemini"
        local["model"] = f"{local.get('model', 'BSJP Lokal')} · Fallback: {err}"
        return local

    return _advise_local(ticker, candidate)


def _advise_local(ticker: str, candidate: dict[str, Any]) -> dict[str, Any]:
    """Analisa BSJP berbasis aturan untuk 1 saham."""
    tk = ticker.upper()
    syariah = candidate.get("syariah", True)
    iep = candidate.get("iep")
    cp = candidate.get("cp")
    gap = candidate.get("gap_iep_cp_pct")
    score = candidate.get("bsjp_score")
    buy_signal = bool(candidate.get("buy_signal"))
    vol = candidate.get("vol_ratio_5d_20d")
    sesi = candidate.get("sesi_label") or "—"
    rec_tv = candidate.get("rec_tv") or "—"
    fund = candidate.get("fundamental") or {}

    if vol is None:
        liq = "TIDAK DIKETAHUI"
    elif vol < 1.0:
        liq = "TINGGI"
    elif vol < 1.5:
        liq = "SEDANG"
    else:
        liq = "RENDAH"

    lines: list[str] = []

    if not syariah:
        analisa = (
            f"❌ {tk} tidak lolos screening syariah. Strategi BSJP hanya untuk saham DES/ISSI "
            "(Fatwa DSN-MUI No. 80/2011 — long-only, tunai)."
        )
        return {
            "enabled": True,
            "ticker": tk,
            "model": "BSJP Lokal (berbasis aturan)",
            "analisa": analisa,
            "verdict": {
                "rekomendasi": "HINDARI",
                "keyakinan": "TINGGI",
                "entry_pre_closing": None,
                "target_pre_opening": None,
                "stop_loss": None,
                "risiko_utama": "Non-syariah",
                "horizon": "overnight (1 hari)",
            },
        }

    lines.append(
        f"📌 BSJP — {tk}\n"
        f"Sesi: {sesi} · Skor BSJP: {score if score is not None else '—'} · "
        f"Sinyal beli: {'YA' if buy_signal else 'TIDAK'} · Rec TV: {rec_tv}."
    )

    gap_txt = f"{gap:+.2f}%" if isinstance(gap, (int, float)) else "—"
    lines.append(
        f"📊 DATA PASAR\n"
        f"• IEP estimasi: {iep if iep is not None else '—'}\n"
        f"• CP kemarin: {cp if cp is not None else '—'}\n"
        f"• Gap IEP vs CP: {gap_txt}\n"
        f"• Volume ratio 5d/20d: {vol if vol is not None else '—'} (risiko likuiditas: {liq})"
    )

    if fund:
        parts = []
        for k in ("roe", "der", "per", "pbv"):
            if fund.get(k) is not None:
                parts.append(f"{k.upper()} {fund[k]}")
        if parts:
            lines.append("📈 FUNDAMENTAL RINGKAS\n• " + " · ".join(parts))

    risiko: list[str] = []
    if liq == "TINGGI":
        risiko.append(
            "PERINGATAN KERAS likuiditas rendah — rawan Fake Bid/Offer di pre-closing, "
            "manipulasi sesi tipis, dan sulit exit di pre-opening (spread lebar)."
        )
    elif liq == "SEDANG":
        risiko.append("Likuiditas sedang — waspadai antrean palsu & slippage overnight.")
    if isinstance(gap, (int, float)) and gap < 0:
        risiko.append(f"IEP di bawah CP ({gap:+.2f}%) — risiko gap down / demand lemah.")
    if not buy_signal:
        risiko.append("Sinyal beli BSJP belum terkonfirmasi dari scanner.")
    risiko.append("Strategi overnight berisiko tinggi: gap down, slippage pre-opening, manipulasi sesi.")
    lines.append("⚠️ RISIKO OVERNIGHT\n" + "\n".join("• " + r for r in risiko))

    # Verdict berbasis skor + sinyal + likuiditas
    if not buy_signal or (isinstance(score, (int, float)) and score < 40):
        rekomendasi, keyakinan = "HINDARI", "SEDANG"
        risiko_utama = "Sinyal BSJP lemah"
    elif liq == "TINGGI":
        rekomendasi, keyakinan = "TAHAN", "TINGGI"
        risiko_utama = "Likuiditas rendah"
    elif buy_signal and isinstance(score, (int, float)) and score >= 70 and liq == "RENDAH":
        rekomendasi, keyakinan = "BELI_KUAT", "TINGGI"
        risiko_utama = "Gap overnight"
    elif buy_signal:
        rekomendasi, keyakinan = "BELI_HATI", "SEDANG"
        risiko_utama = "Gap overnight / likuiditas"
    else:
        rekomendasi, keyakinan = "TAHAN", "SEDANG"
        risiko_utama = "Kondisi belum ideal"

    entry = float(iep) if isinstance(iep, (int, float)) else (float(cp) if isinstance(cp, (int, float)) else None)
    target = None
    stop = None
    if entry is not None and rekomendasi in ("BELI_KUAT", "BELI_HATI"):
        target = round(entry * 1.01, 2)  # target gap-up ~1%
        stop = round(entry * 0.985, 2)  # SL ~1.5%

    lines.append(
        "🎯 SARAN BSJP\n"
        f"• Rekomendasi: {rekomendasi} (keyakinan {keyakinan})\n"
        + (
            f"• Entry pre-closing sekitar {entry:,.0f}; target pre-opening ±{target:,.0f}; "
            f"stop loss ±{stop:,.0f}.".replace(",", ".")
            if entry is not None and target is not None and stop is not None
            else "• Belum ada level entry/exit konkret — tunggu konfirmasi IEP & sinyal."
        )
        + "\n• Beli hanya di pre-closing (15:50–16:00) bila BUY > IEP; jual pagi bila IEP > CP."
    )
    lines.append(
        "ℹ️ Alat bantu analisa BSJP berbasis aturan — BUKAN ajakan jual/beli. "
        "Keputusan & risiko di tangan Anda. Transaksi tunai, long-only, sesuai syariah."
    )

    return {
        "enabled": True,
        "ticker": tk,
        "model": "BSJP Lokal (berbasis aturan)",
        "analisa": "\n\n".join(lines),
        "verdict": {
            "rekomendasi": rekomendasi,
            "keyakinan": keyakinan,
            "entry_pre_closing": entry,
            "target_pre_opening": target,
            "stop_loss": stop,
            "risiko_utama": risiko_utama,
            "horizon": "overnight (1 hari)",
        },
    }
