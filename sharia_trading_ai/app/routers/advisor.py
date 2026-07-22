from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.core import deepseek_advisor, funnel, gemini_advisor, local_advisor

router = APIRouter(prefix="/api", tags=["advisor"])


def _auto_engine() -> str:
    """Urutan auto: Gemini → DeepSeek → Lokal."""
    if gemini_advisor.is_enabled():
        return "gemini"
    if deepseek_advisor.is_enabled():
        return "deepseek"
    return "lokal"


@router.get("/advisor/status")
def advisor_status():
    """Engine yang tersedia & default (auto)."""
    return {
        "default": _auto_engine(),
        "engines": {
            "gemini": {
                "tersedia": gemini_advisor.is_enabled(),
                "biaya": "gratis (free tier, ada kuota RPM/harian)",
                "model": settings.gemini_model,
            },
            "deepseek": {
                "tersedia": deepseek_advisor.is_enabled(),
                "biaya": "berbayar (saldo API DeepSeek)",
                "model": settings.deepseek_model,
            },
            "lokal": {"tersedia": True, "biaya": "gratis (instan, berbasis aturan)"},
        },
    }


@router.get("/advisor/{ticker}")
def advisor(ticker: str, engine: str = "auto"):
    """
    engine: auto | gemini | deepseek | lokal
      auto     → Gemini (jika key) → DeepSeek (jika key) → Lokal.
      gemini   → Google Gemini · gagal/kuota → fallback lokal.
      deepseek → DeepSeek API · gagal → fallback lokal.
      lokal    → berbasis aturan, instan, gratis.
    """
    report = funnel.analyze_stock(ticker)
    eng = _auto_engine() if engine == "auto" else engine

    if eng == "gemini":
        result = gemini_advisor.advise(report)
        if result.get("enabled") is False or result.get("error"):
            err_msg = result.get("error") or result.get("message") or "Unknown"
            result = local_advisor.advise(report)
            result["fallback_dari"] = "gemini"
            result["model"] = f"Analisa Lokal (gratis · Fallback: {err_msg})"
    elif eng == "deepseek":
        result = deepseek_advisor.advise(report)
        if result.get("enabled") is False or result.get("error"):
            err_msg = result.get("error") or result.get("message") or "Unknown"
            result = local_advisor.advise(report)
            result["fallback_dari"] = "deepseek"
            result["model"] = f"Analisa Lokal (gratis · Fallback: {err_msg})"
    else:
        result = local_advisor.advise(report)
        eng = "lokal"

    result["ticker"] = ticker.upper()
    result["engine"] = eng if eng in ("gemini", "deepseek", "lokal") else "lokal"
    result["rekomendasi_mesin"] = report.get("rekomendasi")
    return result


@router.get("/advisor/explain/{ticker}/{metric}")
def explain_metric(ticker: str, metric: str, status: str = "", value: str = "", engine: str = "auto"):
    """
    Menjelaskan arti kriteria tertentu pada saham tertentu.
    Gemini / DeepSeek bila dipilih & tersedia; selain itu penjelasan lokal.
    """
    ticker_upper = ticker.upper().strip()
    report = funnel.analyze_stock(ticker_upper)

    prompt = f"""\
Jelaskan secara ringkas, profesional, dan mudah dipahami dalam Bahasa Indonesia mengenai indikator/kriteria berikut pada saham {ticker_upper}:
- Kriteria/Indikator: {metric}
- Status di Dashboard: {status}
- Nilai Aktual: {value}

Berikan penjelasan tentang:
1. Apa arti kriteria/indikator ini secara teoretis dan praktis dalam pasar modal (khususnya pasar modal Syariah jika relevan).
2. Bagaimana kondisi aktual saham {ticker_upper} berdasarkan kriteria ini (mengapa dia lolos/gagal, apa dampaknya bagi investor).
3. Batasi penjelasan maksimal 150 kata, langsung ke inti penjelasan tanpa basa-basi pembuka/penutup.
"""

    eng = _auto_engine() if engine == "auto" else engine
    if eng == "gemini" and gemini_advisor.is_enabled():
        result = gemini_advisor.explain(prompt)
        if result.get("enabled") and result.get("explanation") and not result.get("error"):
            return result
    if eng == "deepseek" and deepseek_advisor.is_enabled():
        result = deepseek_advisor.explain(prompt)
        if result.get("enabled") and result.get("explanation") and not result.get("error"):
            return result
    if eng == "auto":
        if gemini_advisor.is_enabled():
            result = gemini_advisor.explain(prompt)
            if result.get("enabled") and result.get("explanation") and not result.get("error"):
                return result
        if deepseek_advisor.is_enabled():
            result = deepseek_advisor.explain(prompt)
            if result.get("enabled") and result.get("explanation") and not result.get("error"):
                return result

    explanation = _local_explanation(ticker_upper, metric, status, value, report)
    return {"enabled": True, "model": "Penjelasan Lokal (gratis)", "explanation": explanation}


def _local_explanation(ticker: str, metric: str, status: str, value: str, report: dict) -> str:
    m_lower = metric.lower()
    name = report.get("name") or ticker

    if "syariah" in m_lower or "sharia" in m_lower:
        if "lolos" in status.lower() or "halal" in status.lower() or "compliant" in status.lower() or "true" in status.lower() or "✓" in status.lower():
            return (f"Saham {ticker} ({name}) dinyatakan HALAL/Syariah karena terdaftar dalam Daftar Efek Syariah (DES) "
                    "oleh OJK & DSN-MUI. Bisnis utamanya tidak melanggar syariah (bukan bank konvensional, judi, alkohol, rokok, dll.), "
                    "serta rasio keuangan memenuhi syarat: Utang Berbasis Riba/Aset <= 45% dan Pendapatan Non-Halal/Pendapatan <= 10%.")
        else:
            return (f"Saham {ticker} ({name}) berstatus Non-Syariah (Haram) karena melanggar kriteria bisnis syariah "
                    "atau rasio keuangan (misal: utang berbasis riba di atas 45% dari total aset). Investor Muslim dilarang membeli saham ini.")

    if "roa" in m_lower:
        desc = (f"ROA (Return on Assets) mengukur efisiensi perusahaan dalam menghasilkan laba bersih dari total asetnya. "
                f"Di dashboard, target minimal adalah 15% (sesuai standar 6 Magic Number). Nilai ROA {ticker} adalah {value}. ")
        if "lolos" in status.lower() or "true" in status.lower():
            return desc + f"Status: Lolos. Ini berarti {ticker} sangat efisien dalam menggunakan asetnya untuk menghasilkan keuntungan."
        else:
            return desc + f"Status: Gagal. Ini berarti efisiensi pemanfaatan aset {ticker} masih di bawah standar prima yang diharapkan."

    if "roe" in m_lower:
        desc = (f"ROE (Return on Equity) mengukur profitabilitas perusahaan dari modal yang disetor pemegang saham. "
                f"Target minimal adalah 15% (6 Magic Number). Nilai ROE {ticker} adalah {value}. ")
        if "lolos" in status.lower() or "true" in status.lower():
            return desc + f"Status: Lolos. Menunjukkan perusahaan mampu mengelola modal pemegang saham dengan profitabilitas tinggi."
        else:
            return desc + f"Status: Gagal. Efisiensi pengelolaan modal untuk mencetak laba bersih dinilai masih kurang optimal."

    if "pbv" in m_lower:
        desc = (f"PBV (Price to Book Value) membandingkan harga saham dengan nilai buku per saham. "
                f"Target PBV murah adalah < 1.0 (atau di bawah 2.0 secara linier). PBV {ticker} saat ini adalah {value}. ")
        if "lolos" in status.lower() or "true" in status.lower():
            return desc + f"Status: Lolos. Berarti harga saham dinilai murah/undervalue dibandingkan aset bersih perusahaan."
        else:
            return desc + f"Status: Gagal. Berarti harga saham sudah premium/mahal dibanding aset bersihnya."

    if "per" in m_lower:
        desc = (f"PER (Price to Earnings Ratio) membandingkan harga saham dengan laba per saham (EPS). "
                f"Secara teori, ini adalah estimasi berapa tahun investasi Anda akan balik modal. Target murah adalah < 10x. PER {ticker} saat ini adalah {value}. ")
        if "lolos" in status.lower() or "true" in status.lower():
            return desc + f"Status: Lolos. Valuasi harga dibanding laba bersih dinilai murah dan menarik untuk diinvestasikan."
        else:
            return desc + f"Status: Gagal. Valuasi harga dinilai mahal dibanding kemampuan mencetak laba bersih saat ini."

    if "der" in m_lower:
        desc = (f"DER (Debt to Equity Ratio) menunjukkan rasio utang dibanding modal perusahaan. "
                f"Target aman adalah < 1.0 atau < 100% (bahkan DER rendah makin baik). DER {ticker} saat ini adalah {value}. ")
        if "lolos" in status.lower() or "true" in status.lower():
            return desc + f"Status: Lolos. Tingkat utang perusahaan masih dalam batas aman/rendah dibanding modal sendiri."
        else:
            return desc + f"Status: Gagal. Perusahaan memiliki tingkat utang yang relatif tinggi dibanding modal, yang meningkatkan risiko finansial."

    if "peg" in m_lower:
        desc = (f"PEG (Price/Earnings-to-Growth) membandingkan rasio PER dengan tingkat pertumbuhan laba bersih. "
                f"Rasio < 1.0 menunjukkan saham undervalued mengingat potensi pertumbuhannya. PEG {ticker} saat ini adalah {value}. ")
        if "lolos" in status.lower() or "true" in status.lower():
            return desc + f"Status: Lolos. Harga saham saat ini murah jika dinilai berdasarkan pertumbuhan laba bersihnya."
        else:
            return desc + f"Status: Gagal. Saham dinilai mahal karena pertumbuhan labanya tidak mengimbangi rasio PER saat ini."

    if "eps" in m_lower:
        desc = (f"Pertumbuhan EPS mengukur peningkatan laba per lembar saham secara tahunan (YoY). "
                f"Target pertumbuhan positif (EPS growth > 0%). Nilai pertumbuhan EPS {ticker} saat ini adalah {value}. ")
        if "lolos" in status.lower() or "true" in status.lower():
            return desc + f"Status: Lolos. Perusahaan sukses membukukan peningkatan laba bersih operasional."
        else:
            return desc + f"Status: Gagal. Laba bersih per lembar saham mengalami penurunan atau minus dibanding tahun lalu."

    if "dividend" in m_lower or "yield" in m_lower:
        desc = (f"Dividend Yield menunjukkan persentase dividen tahunan terhadap harga saham saat ini. "
                f"Target dividen premium adalah > 7%. Nilai Dividend Yield {ticker} adalah {value}. ")
        if "lolos" in status.lower() or "true" in status.lower():
            return desc + f"Status: Lolos. Dividen yang dibagikan tergolong besar dan sangat menarik bagi investor bertipe dividend hunter."
        else:
            return desc + f"Status: Gagal / Sedang. Imbal hasil dividen dinilai biasa saja atau tidak memenuhi target minimal 7%."

    return (f"Kriteria {metric} pada saham {ticker} ({name}) memiliki status '{status}' dengan nilai '{value}'. "
            "Kriteria ini merupakan bagian dari evaluasi multi-faktor sistem (Fundamental / CAN SLIM / Teknikal) "
            "untuk menilai kelayakan investasi saham berdasarkan aturan baku investasi syariah.")
