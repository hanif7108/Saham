"""
AI Advisor (opsional) — Claude sebagai ANALIS + KALIBRATOR di atas funnel.

Dua peran:
  1. Narator analis — mengubah skor mentah (6 Magic Number, CAN SLIM, teknikal,
     bandarmologi, Jalur 7%, dividen, price action) menjadi narasi analisa +
     saran trading plan berbahasa Indonesia, dalam koridor syariah.
  2. Kalibrator — menilai SECARA INDEPENDEN, lalu mengeluarkan VERDICT terstruktur
     (rekomendasi, keyakinan, setuju/lebih konservatif/lebih agresif vs mesin,
     penyesuaian conviction, risiko utama) yang di-parse aplikasi.

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

Manfaatkan SELURUH konteks untuk penalaran yang lebih dalam (bukan hanya skor):
- 'price_action': pola harga terkini, momentum (1mgg/1bln/3bln), posisi vs 52-week
  high/low, dan tren volume — baca arah & kekuatan tren sebenarnya.
- 'bandarmologi': indikasi akumulasi/distribusi bandar.
- 'jalur7': kelayakan target profit Jalur 7%.
- 'dividen': profil & jadwal dividen (relevan utk strategi tahan-dividen).
- 'cross_check_tradingview': rekomendasi teknikal independen TradingView.
Bila ada sinyal SALING BERTENTANGAN (mis. fundamental kuat tapi teknikal SELL,
atau harga uptrend tapi bandar distribusi), TUNJUKKAN dan jelaskan cara Anda
menimbangnya.

Bila tersedia field 'track_record_simulasi' (hasil paper-trade otomatis atas
rekomendasi aplikasi ini), gunakan untuk MENGKALIBRASI keyakinan saran Anda:
win-rate rendah → lebih konservatif & tekankan manajemen risiko; win-rate
tinggi pada band conviction tertentu → sebut konteksnya secara singkat.

PERAN KALIBRATOR: Anda menilai secara independen, bukan sekadar mengulang mesin.
Bila bukti menunjukkan 'rekomendasi_mesin' terlalu agresif atau terlalu konservatif,
nyatakan dengan jelas beserta alasannya.

Jangan mengarang angka yang tidak ada di data. Jika data 'n/a', sebut keterbatasannya.
Ringkas (maksimal ~400 kata untuk narasi), tanpa basa-basi pembuka.

WAJIB diakhiri TEPAT dengan SATU baris machine-readable (tidak ada teks apa pun
setelahnya), format persis:
@@VERDICT@@ {"rekomendasi_claude":"<STRONG BUY|BUY|ACCUMULATE|HOLD|WAIT|AVOID>","keyakinan":"<TINGGI|SEDANG|RENDAH>","vs_mesin":"<SETUJU|LEBIH_KONSERVATIF|LEBIH_AGRESIF>","penyesuaian_conviction":<bilangan bulat -3..3>,"entry_ideal":<harga|null>,"stop_loss":<harga|null>,"target_harga":<harga|null>,"rrr":"<mis. 1:2.5|null>","horizon":"<mis. swing 1-4 minggu|null>","risiko_utama":"<maks 12 kata>"}
Aturan:
- 'penyesuaian_conviction' = seberapa besar Anda menggeser skor keyakinan mesin
  (negatif = turunkan, 0 = setuju, positif = naikkan).
- 'entry_ideal'/'stop_loss'/'target_harga' = ANGKA harga rupiah konseptual, HANYA
  bila rekomendasi beli-layak (STRONG BUY/BUY/ACCUMULATE); selain itu null. Turunkan
  dari level support/resistance, ATR, atau Jalur 7% pada data. RRR minimal 1:2.
- 'horizon' = kerangka waktu (scalping/harian, swing 1-4 minggu, atau posisi/bulanan).
- JSON harus VALID, satu baris, tanda kutip ganda. Saham non-syariah → AVOID + semua
  harga null.
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


VERDICT_MARKER = "@@VERDICT@@"


def _price_context(ticker: str) -> Any:
    """Ringkasan price action terkini agar Claude 'melihat' pergerakan harga,
    bukan hanya indikator. Opsional — None bila data tak cukup."""
    try:
        from app.data import provider
        hist = provider.get_history(ticker)
        if hist is None or hist.empty or "Close" not in hist:
            return None
        close = hist["Close"].astype(float).dropna()
        if len(close) < 10:
            return None
        last = float(close.iloc[-1])

        def _chg(n: int):
            if len(close) > n:
                p = float(close.iloc[-1 - n])
                return round((last - p) / p * 100, 2) if p else None
            return None

        hi52 = float(close.tail(252).max())
        lo52 = float(close.tail(252).min())
        vol_trend = None
        if "Volume" in hist:
            vol = hist["Volume"].astype(float).dropna()
            if len(vol) >= 20 and float(vol.tail(20).mean()):
                vol_trend = round(float(vol.tail(5).mean()) / float(vol.tail(20).mean()), 2)
        return {
            "harga_terakhir": round(last, 2),
            "perubahan_pct": {"1hr": _chg(1), "1mgg": _chg(5), "1bln": _chg(20), "3bln": _chg(60)},
            "posisi_52w": {
                "high": round(hi52, 2), "low": round(lo52, 2),
                "pct_dari_high": round((last - hi52) / hi52 * 100, 2) if hi52 else None,
                "pct_dari_low": round((last - lo52) / lo52 * 100, 2) if lo52 else None,
            },
            "12_close_terakhir": [round(float(x), 2) for x in close.tail(12)],
            "rasio_volume_5d_vs_20d": vol_trend,
        }
    except Exception:  # noqa: BLE001
        return None


def _split_verdict(text: str) -> tuple[str, Any]:
    """Pisahkan narasi dari baris @@VERDICT@@ {json}. Kembalikan (narasi, verdict|None)."""
    idx = text.rfind(VERDICT_MARKER)
    if idx == -1:
        return text.strip(), None
    head = text[:idx].strip()
    tail = text[idx + len(VERDICT_MARKER):]
    try:
        start, end = tail.find("{"), tail.rfind("}")
        verdict = json.loads(tail[start:end + 1]) if (start != -1 and end != -1) else None
    except Exception:  # noqa: BLE001
        verdict = None
    return head, verdict


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
        "sinyal_oneill": report.get("signal"),
        "jalur7": report.get("jalur7"),
        "bandarmologi": report.get("bandarmologi"),
        "rekomendasi_mesin": report.get("rekomendasi"),
    }
    # Konteks DALAM tambahan (price action, dividen) untuk penalaran yang lebih kaya.
    pa = _price_context(report.get("ticker", ""))
    if pa:
        slim["price_action"] = pa
    try:
        from app.core import dividend
        prof = dividend.profile(report.get("ticker", ""))
        if prof:
            slim["dividen"] = prof
    except Exception:  # noqa: BLE001
        pass
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
        "max_tokens": 3500,
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
    analisa, verdict = _split_verdict(text)   # pisahkan narasi & verdict kalibrator
    usage = getattr(resp, "usage", None)
    return {
        "enabled": True,
        "model": settings.ai_model,
        "analisa": analisa,
        "verdict": verdict,                   # {"rekomendasi_claude", "keyakinan", "vs_mesin", ...} | None
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        } if usage else None,
    }
