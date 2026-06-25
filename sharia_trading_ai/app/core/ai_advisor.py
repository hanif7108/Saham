"""
AI Advisor (opsional) — Claude menjelaskan hasil funnel dalam bahasa natural.

Mengubah skor mentah (6 Magic Number, CAN SLIM, teknikal) menjadi narasi analisa
+ saran trading plan berbahasa Indonesia, tetap dalam koridor syariah.

Pluggable: aktif hanya jika ANTHROPIC_API_KEY tersedia (di .env atau environment).
Tanpa key, endpoint mengembalikan pesan ramah, bukan error.

Praktik: prompt caching (methodology stabil di system prompt), adaptive thinking,
model claude-opus-4-8.
"""

from __future__ import annotations

import json
import os
from typing import Any

from app.config import settings

# System prompt STABIL (tidak ada tanggal/nilai volatil) -> bisa di-cache.
SYSTEM_PROMPT = """\
Anda adalah asisten analis saham SYARIAH untuk Bursa Efek Indonesia (BEI),
mengikuti metodologi "Sharia Investment and Trading Module" (YLive Academy) dan
Fatwa DSN-MUI No. 40/2003 & No. 80/2011.

Prinsip yang WAJIB Anda pegang:
- Hanya saham yang lolos screening syariah (DES/ISSI). Tolak saran pada saham non-syariah.
- Transaksi TUNAI, long-only: tanpa margin (riba), tanpa short selling, tanpa
  bai' al-ma'dum, najsy, ghisysy, insider trading, atau pump-and-dump.
- Kerangka keputusan:
  * Fundamental "6 Magic Number": EPS+, ROA>15%, ROE>15%, DER<1, PBV<1, PER<10x;
    bonus Dividend Yield>7%.
  * CAN SLIM: C (EPS kuartal YoY>25%), A (EPS tahunan>25% & ROE>17%), N (dekat ATH
    + volume), S (cap & free float), L (leader vs IHSG), I (institusi), M (IHSG vs SMA200).
  * Teknikal: tren via SMA200, Stochastic (golden/dead cross, OB>80/OS<20),
    support/resistance, sinyal entry (FBO, 52WBO, BOR, BDTL, Buy-on-Pullback/Dips, Gap Up).
  * Money management: Taichi (OB1/OB2/OB3), RRR minimal 1:2, hanya pakai uang dingin.

Tugas: dari data terstruktur sebuah saham, tuliskan analisa ringkas, jujur, dan
seimbang dalam Bahasa Indonesia, dengan struktur:
1. Ringkasan & status syariah.
2. Kekuatan (poin yang lolos).
3. Kelemahan / risiko (poin yang gagal / data kurang). **PENTING**: Jika volume transaksi harian saham rendah atau likuiditasnya bertanda 'Sangat Tinggi'/'Sedang', berikan peringatan konkret tentang risiko likuiditas (sulit menjual kembali), bahaya jebakan Fake Bid / Fake Offer (antrean palsu), bias analisis order book (antrean tidak mencerminkan tren sebenarnya), dan manipulasi saat sesi pre-closing (khususnya untuk strategi Beli Sore Jual Pagi / BSJP).
4. Pandangan teknikal & timing.
5. Saran trading plan ringkas BILA layak (level entry/CL/TP konseptual, RRR), atau
   alasan menunggu. Tegaskan transaksi tunai (non-margin).
6. Satu kalimat disclaimer: ini alat bantu analisa, bukan ajakan jual/beli; keputusan
   & risiko di tangan pengguna.

Bila tersedia field 'track_record_simulasi' (hasil paper-trade otomatis atas
rekomendasi aplikasi ini), gunakan untuk MENGKALIBRASI keyakinan saran Anda:
win-rate rendah → lebih konservatif & tekankan manajemen risiko; win-rate
tinggi pada band conviction tertentu → sebut konteksnya secara singkat.

Jangan mengarang angka yang tidak ada di data. Jika data 'n/a', sebut keterbatasannya.
Ringkas (maksimal ~400 kata), tanpa basa-basi pembuka.
"""


def is_enabled() -> bool:
    return bool(settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"))


def _disabled_payload() -> dict[str, Any]:
    return {
        "enabled": False,
        "message": (
            "AI Advisor nonaktif. Set ANTHROPIC_API_KEY di file .env "
            "(atau environment) lalu jalankan ulang server untuk mengaktifkan."
        ),
    }


def _format_report(report: dict[str, Any]) -> str:
    """Data per-saham (VOLATIL) -> diletakkan di user turn, bukan system prompt."""
    slim = {
        "ticker": report.get("ticker"),
        "name": report.get("name"),
        "sector": report.get("sector"),
        "syariah": {
            "compliant": report["sharia"]["compliant"],
            "in_des": report["sharia"]["in_des"],
        },
        "fundamental_6_magic": {
            "skor": f"{report['fundamental']['magic_score']}/6",
            "verdict": report["fundamental"]["verdict"],
            "rasio": report["fundamental"]["raw"],
            "sumber_data": report["fundamental"].get("source"),
        },
        # Cross-check teknikal independen dari TradingView (None bila sumber data
        # tidak memakai TradingView). Pakai untuk MENGKALIBRASI keyakinan timing:
        # bila fundamental kuat tapi teknikal TV SELL kuat, tekankan risiko timing.
        "cross_check_tradingview": report["fundamental"].get("tradingview"),
        "canslim": {
            "skor": f"{report['canslim']['canslim_score']}/7",
            "verdict": report["canslim"]["verdict"],
            "letters": {k: v["nilai"] + (" (LOLOS)" if v["lolos"] else "")
                        for k, v in report["canslim"]["letters"].items()},
        },
        "teknikal": report.get("technical"),
        "rekomendasi_mesin": report.get("rekomendasi"),
    }
    # Track-record SIMULASI eksekusi harian (paper trade) → Claude belajar dari
    # akurasi prediksi aplikasi sebelumnya (lazy import, opsional).
    try:
        from app.core import simulation
        track = simulation.summary_for_ai()
        if track:
            slim["track_record_simulasi"] = track
    except Exception:  # noqa: BLE001
        pass
    return ("Analisa saham berikut sesuai metodologi & koridor syariah. "
            "Data terstruktur:\n\n" + json.dumps(slim, ensure_ascii=False, indent=2))


def advise(report: dict[str, Any]) -> dict[str, Any]:
    if not is_enabled():
        return _disabled_payload()

    try:
        import anthropic
    except ImportError:
        return {"enabled": False, "message": "Paket 'anthropic' belum terpasang (pip install anthropic)."}

    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    kwargs: dict[str, Any] = {
        "model": settings.ai_model,
        "max_tokens": 3000,
        "system": [{"type": "text", "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": _format_report(report)}],
    }
    # Adaptive thinking + effort hanya untuk model yang mendukung (opus/sonnet 4.6+).
    if settings.ai_model.startswith(("claude-opus", "claude-sonnet")):
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "medium"}

    try:
        resp = client.messages.create(**kwargs)
    except TypeError:
        # SDK lama tak kenal thinking/output_config -> coba tanpa itu.
        kwargs.pop("thinking", None)
        kwargs.pop("output_config", None)
        resp = client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001
        return {"enabled": True, "error": f"Gagal memanggil Claude: {e}"}

    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    usage = getattr(resp, "usage", None)
    return {
        "enabled": True,
        "model": settings.ai_model,
        "analisa": text.strip(),
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        } if usage else None,
    }
