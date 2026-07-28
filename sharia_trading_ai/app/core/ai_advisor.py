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

VERDICT_MARKER = "@@VERDICT@@"

# System prompt STABIL (tidak ada tanggal/nilai volatil) -> bisa di-cache.
SYSTEM_PROMPT = """\
Anda adalah asisten analis saham SYARIAH untuk Bursa Efek Indonesia (BEI),
mengikuti metodologi "Sharia Investment and Trading Module" (YLive Academy) dan
Fatwa DSN-MUI No. 40/2003 & No. 80/2011.

Prinsip yang WAJIB Anda pegang:
- Hanya saham yang lolos screening syariah (DES/ISSI). Tolak saran pada saham non-syariah.
- Transaksi TUNAI, long-only: tanpa margin (riba), tanpa short selling, tanpa
  bai' al-ma'dum, najsy, ghisysy, insider trading, atau pump-and-dump.
- DATA TEKNIKAL WAJIB dari payload (jangan mengarang angka):
  * Pakai 'teknikal.price', 'teknikal.rsi', 'teknikal.stochastic', 'signal.rsi'
    PERSIS seperti yang dikirim. Jangan ganti dengan memori/training Anda.
  * Sebut sumber: IDX / yfinance (lihat teknikal.data_source). Harga BEI dalam Rupiah
    (mis. TINS ≈ ribuan rupiah, BUKAN puluhan).
  * Bila data di payload bertentangan dengan 'intuisi' Anda, PERCAYAI payload.
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
5. Saran money management & trading plan bertahap (metode Taichi OB1/OB2/OB3) BILA layak beli (BUY/ACCUMULATE/SPECULATIVE BUY). Hubungkan dengan saldo cash RDN Anda ('data_akun_dan_cash') dan hitung nilai Rupiah dan Lot riil untuk setiap tahap pembelian (OB1, OB2, OB3) berdasarkan porsi alokasi dana per emiten. Berikan perkiraan waktu masuk ke tahap berikutnya (misal: "tahap 2 jika RSI menyentuh oversold < 30", atau "tahap 3 saat breakout re-entry"). Jika Anda sudah memiliki saham ini di portofolio ('portofolio_aktif_anda'), berikan rekomendasi hold atau average up/down berdasarkan tingkat keuntungan/kerugian (P/L) saat ini. Tegaskan transaksi tunai (non-margin). Jika kondisi urgent/mendesak (seperti menyentuh level stop-loss keras -7% atau breakdown support besar), infokan bahwa alert/notifikasi darurat otomatis akan dikirim ke Telegram Anda.
6. Satu kalimat disclaimer: ini alat bantu analisa, bukan ajakan jual/beli; keputusan
   & risiko di tangan pengguna.

Manfaatkan SELURUH konteks untuk penalaran yang lebih dalam (bukan hanya skor):
- 'price_action': pola harga terkini, momentum (1mgg/1bln/3bln), posisi vs 52-week
  high/low, dan tren volume — baca arah & kekuatan tren sebenarnya.
- 'bandarmologi': indikasi akumulasi/distribusi bandar.
- 'jalur7': kelayakan target profit Jalur 7%.
- 'dividen': profil & jadwal dividen (relevan utk strategi tahan-dividen).
- 'cross_check_tradingview': rekomendasi teknikal independen TradingView.
- 'sinyal_ml': prediksi model LightGBM (horizon N hari bursa, tervalidasi
  walk-forward). p_buy/p_hold/p_sell = probabilitas; 'confident' true berarti
  melewati ambang keyakinan. Jelaskan sinyal ini lewat 'top_features'
  (fitur paling berpengaruh + nilai saat ini) — JANGAN mengarang angka
  atau menyebut prediksi harga spesifik yang tidak ada di data.
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
@@VERDICT@@ {"rekomendasi":"<STRONG BUY|BUY|ACCUMULATE|HOLD|WAIT|AVOID>","keyakinan":"<TINGGI|SEDANG|RENDAH>","vs_mesin":"<SETUJU|LEBIH_KONSERVATIF|LEBIH_AGRESIF>","penyesuaian_conviction":<bilangan bulat -3..3>,"entry_ideal":<harga|null>,"stop_loss":<harga|null>,"target_harga":<harga|null>,"rrr":"<mis. 1:2.5|null>","horizon":"<mis. swing 1-4 minggu|null>","risiko_utama":"<maks 12 kata>"}
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
    return False


def _disabled_payload() -> dict[str, Any]:
    return {
        "enabled": False,
        "message": "Claude AI Advisor dinonaktifkan. Gunakan Advisor Lokal (berbasis aturan).",
    }


def _price_context(ticker: str) -> Any:
    """Ringkasan price action terkini agar LLM 'melihat' pergerakan harga,
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
    from app.data import provider

    market_trend_str = "UPTREND (Bullish)"
    try:
        idx_df = provider.get_index_history(period="5y")
        if idx_df is not None and not idx_df.empty and len(idx_df) >= 200:
            close_val = float(idx_df["Close"].iloc[-1])
            sma200_val = float(idx_df["Close"].rolling(200).mean().iloc[-1])
            market_trend_str = f"UPTREND (Bullish) - IHSG ({close_val:.0f}) > SMA200 ({sma200_val:.0f})" if close_val > sma200_val else f"DOWNTREND (Bearish) - IHSG ({close_val:.0f}) <= SMA200 ({sma200_val:.0f})"
    except Exception:
        pass

    slim = {
        "ticker": report.get("ticker"),
        "name": report.get("name"),
        "sector": report.get("sector"),
        "kondisi_pasar_ihsg": market_trend_str,
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
        # Sinyal ML LightGBM (walk-forward validated). Jelaskan dari
        # top_features (fitur paling berpengaruh) — jangan mengarang angka.
        "sinyal_ml": report.get("ml_signal"),
    }
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
    try:
        from app.core import simulation
        track = simulation.summary_for_ai()
        if track:
            slim["track_record_simulasi"] = track
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.core import portfolio
        port_data = portfolio.list_positions()
        positions = port_data.get("positions", [])
        holding = next((p for p in positions if p["ticker"] == report.get("ticker")), None)
        if holding:
            slim["portofolio_aktif_anda"] = {
                "lots": holding.get("lots"),
                "avg_price": holding.get("avg_price"),
                "net_pl": holding.get("net_pl"),
                "net_pl_pct": holding.get("net_pl_pct"),
                "net_value": holding.get("net_value"),
                "broker": holding.get("broker")
            }
        else:
            slim["portofolio_aktif_anda"] = None
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.core import accounts
        acc_data = accounts.breakdown()
        rdns = acc_data.get("rdn", [])
        slim["data_akun_dan_cash"] = [
            {
                "broker": r.get("broker"),
                "rdn": r.get("rdn"),
                "cash": r.get("cash"),
                "cash_at_rdn": r.get("cash_at_rdn"),
                "target_emiten": r.get("target_emiten"),
                "advice": r.get("advice")
            } for r in rdns
        ]
    except Exception:  # noqa: BLE001
        pass

    return ("Analisa saham berikut sesuai metodologi & koridor syariah. "
            "Data terstruktur:\n\n" + json.dumps(slim, ensure_ascii=False, indent=2))


def advise(report: dict[str, Any], force: bool = False) -> dict[str, Any]:
    return _disabled_payload()
