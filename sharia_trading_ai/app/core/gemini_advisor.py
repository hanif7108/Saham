"""
Advisor via Google Gemini (free tier — Google AI Studio).

Memakai system prompt & format data yang sama dengan engine Claude, lewat REST API
`generativelanguage.googleapis.com` (tanpa SDK). Aktif bila GEMINI_API_KEY di-set.

Model default: gemini-2.5-flash. thinkingBudget=0 agar token tidak habis untuk
reasoning internal. Bila kuota/RPM habis → caller fallback ke Advisor Lokal.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.config import settings
from app.core.ai_advisor import SYSTEM_PROMPT, _format_report, _split_verdict

BASE = "https://generativelanguage.googleapis.com/v1beta/models"

SYSTEM_PROMPT_BSJP = """\
Anda adalah analis strategi BSJP (Beli Saat Pre-closing, Jual Pagi Hari) untuk \
Bursa Efek Indonesia (BEI), dalam koridor syariah (long-only, tunai — Fatwa DSN-MUI No. 80/2011).

Strategi BSJP:
• BELI saat pre-closing (15:50–16:00 WIB): bila BUY_price > IEP (demand kuat)
• JUAL pagi hari (08:45–09:00 WIB): bila IEP_pagi > CP_kemarin (gap-up terkonfirmasi)
• IEP = Indicative Equilibrium Price (harga keseimbangan estimasi saat pre-closing/pre-opening)

Prinsip WAJIB:
- Hanya saham DES/ISSI (syariah). Tolak BSJP pada saham non-syariah.
- Long-only, tunai — tanpa margin, tanpa short selling.
- Strategi ini berisiko TINGGI: gap down overnight, slippage pre-opening, manipulasi sesi.

Tugas Anda: dari data terstruktur saham, berikan analisa BSJP singkat dalam Bahasa Indonesia:
1. Kelayakan BSJP untuk saham ini (skor & kondisi pasar saat ini)
2. Risiko utama overnight yang spesifik (gap down, sentimen global, likuiditas)
3. WAJIB: bila volume rendah atau likuiditas rendah → berikan PERINGATAN KERAS tentang:
   - Jebakan Fake Bid/Fake Offer saat pre-closing
   - Manipulasi harga di sesi tipis
   - Sulitnya eksekusi sell di pre-opening (spread lebar)
4. Level entry konkret (harga beli pre-closing) dan exit (harga jual target pre-opening)
5. Satu kalimat disclaimer syariah

WAJIB diakhiri TEPAT dengan SATU baris machine-readable:
@@BSJP_VERDICT@@ {"rekomendasi":"<BELI_KUAT|BELI_HATI|TAHAN|HINDARI>","keyakinan":"<TINGGI|SEDANG|RENDAH>","entry_pre_closing":<harga|null>,"target_pre_opening":<harga|null>,"stop_loss":<harga|null>,"risiko_utama":"<maks 10 kata>","horizon":"overnight (1 hari)"}

Ringkas (maks 300 kata). Tanpa basa-basi pembuka.
"""

BSJP_VERDICT_MARKER = "@@BSJP_VERDICT@@"


def _key() -> str:
    return (settings.gemini_api_key or os.getenv("GEMINI_API_KEY", "")).strip()


def is_enabled() -> bool:
    return bool(_key())


def _call_gemini(system: str, user: str, *, max_tokens: int = 1500, temperature: float = 0.4) -> dict[str, Any]:
    """Panggil Gemini generateContent. Return {ok, text, usage} atau {ok:False, error}."""
    key = _key()
    if not key:
        return {"ok": False, "error": "GEMINI_API_KEY belum di-set."}

    url = f"{BASE}/{settings.gemini_model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            # model 2.5 = thinking → matikan agar token tak habis utk reasoning & lebih cepat
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        r = httpx.post(url, params={"key": key}, json=payload, timeout=60)
        data = r.json()
        if r.status_code != 200:
            err = (data.get("error") or {}).get("message", f"HTTP {r.status_code}")
            return {"ok": False, "error": f"Gemini: {err}"}
        cands = data.get("candidates") or []
        if not cands:
            fb = (data.get("promptFeedback") or {}).get("blockReason")
            return {
                "ok": False,
                "error": f"Gemini tidak mengembalikan jawaban{f' (diblokir: {fb})' if fb else ''}.",
            }
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            return {"ok": False, "error": "Gemini mengembalikan respons kosong."}
        usage = data.get("usageMetadata") or {}
        return {
            "ok": True,
            "text": text,
            "usage": {
                "output_tokens": usage.get("candidatesTokenCount"),
                "input_tokens": usage.get("promptTokenCount"),
            },
        }
    except httpx.TimeoutException:
        return {"ok": False, "error": "Gemini timeout."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Gagal memanggil Gemini: {e}"}


def advise(report: dict[str, Any]) -> dict[str, Any]:
    if not is_enabled():
        return {
            "enabled": False,
            "message": (
                "Gemini nonaktif. Set GEMINI_API_KEY di .env "
                "(gratis di aistudio.google.com), lalu restart server."
            ),
        }

    res = _call_gemini(SYSTEM_PROMPT, _format_report(report))
    if not res.get("ok"):
        return {"enabled": True, "error": res.get("error", "Gemini gagal.")}

    text = res["text"]
    analisa, verdict = _split_verdict(text)
    # Normalisasi: UI & decisions sering baca rekomendasi_claude
    if isinstance(verdict, dict) and "rekomendasi" in verdict and "rekomendasi_claude" not in verdict:
        verdict = {**verdict, "rekomendasi_claude": verdict.get("rekomendasi")}

    return {
        "enabled": True,
        "model": f"Gemini · {settings.gemini_model} (free tier)",
        "analisa": analisa or text,
        "verdict": verdict,
        "usage": res.get("usage") or {},
    }


def explain(prompt: str) -> dict[str, Any]:
    """Penjelasan singkat indikator (untuk /advisor/explain)."""
    if not is_enabled():
        return {"enabled": False, "error": "Gemini nonaktif."}
    system = (
        "Anda adalah asisten analis saham Syariah BEI yang handal, ringkas, dan to-the-point. "
        "Jawab dalam Bahasa Indonesia, maks 150 kata, tanpa basa-basi."
    )
    res = _call_gemini(system, prompt, max_tokens=400, temperature=0.3)
    if not res.get("ok"):
        return {"enabled": True, "error": res.get("error")}
    return {
        "enabled": True,
        "model": f"Gemini · {settings.gemini_model}",
        "explanation": res["text"],
        "usage": res.get("usage") or {},
    }


def _split_bsjp_verdict(text: str) -> tuple[str, Any]:
    idx = text.rfind(BSJP_VERDICT_MARKER)
    if idx == -1:
        # fallback: coba VERDICT biasa
        return _split_verdict(text)
    head = text[:idx].strip()
    tail = text[idx + len(BSJP_VERDICT_MARKER):]
    try:
        start, end = tail.find("{"), tail.rfind("}")
        verdict = json.loads(tail[start:end + 1]) if (start != -1 and end != -1) else None
    except Exception:  # noqa: BLE001
        verdict = None
    return head, verdict


def _format_bsjp_payload(ticker: str, candidate: dict[str, Any]) -> str:
    payload = {
        "ticker": ticker.upper(),
        "strategi": "BSJP — Beli Pre-closing, Jual Pagi Hari",
        "sesi_saat_ini": candidate.get("sesi_label", "—"),
        "data_pasar": {
            "iep_estimasi": candidate.get("iep"),
            "cp_kemarin": candidate.get("cp"),
            "gap_iep_cp_pct": candidate.get("gap_iep_cp_pct"),
            "bsjp_score": candidate.get("bsjp_score"),
            "buy_signal": candidate.get("buy_signal"),
            "rekomendasi_tv": candidate.get("rec_tv"),
            "volume_ratio_5d_20d": candidate.get("vol_ratio_5d_20d"),
        },
        "fundamental": candidate.get("fundamental", {}),
        "syariah": candidate.get("syariah", True),
        "risiko_likuiditas": (
            "TINGGI" if (candidate.get("vol_ratio_5d_20d") or 0) < 1.0 else
            "SEDANG" if (candidate.get("vol_ratio_5d_20d") or 0) < 1.5 else
            "RENDAH"
        ),
    }
    try:
        from app.data import provider
        hist = provider.get_history(ticker)
        if hist is not None and not hist.empty and "Close" in hist:
            close = hist["Close"].astype(float).dropna()
            if len(close) >= 5:
                last = float(close.iloc[-1])
                hi52 = float(close.tail(252).max())
                lo52 = float(close.tail(252).min())
                payload["price_context"] = {
                    "harga_terakhir": round(last, 2),
                    "posisi_52w": {
                        "high": round(hi52, 2),
                        "low": round(lo52, 2),
                        "pct_dari_high": round((last - hi52) / hi52 * 100, 2) if hi52 else None,
                    },
                    "5_close_terakhir": [round(float(x), 2) for x in close.tail(5)],
                }
    except Exception:  # noqa: BLE001
        pass

    return (
        f"Analisa BSJP untuk saham {ticker.upper()}. Data:\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def advise_bsjp(ticker: str, candidate: dict[str, Any]) -> dict[str, Any]:
    if not is_enabled():
        return {
            "enabled": False,
            "message": "Gemini nonaktif. Set GEMINI_API_KEY di .env (aistudio.google.com).",
        }

    res = _call_gemini(SYSTEM_PROMPT_BSJP, _format_bsjp_payload(ticker, candidate), max_tokens=1200)
    if not res.get("ok"):
        return {"enabled": True, "error": res.get("error", "Gemini gagal.")}

    text = res["text"]
    analisa, verdict = _split_bsjp_verdict(text)
    return {
        "enabled": True,
        "ticker": ticker.upper(),
        "model": f"Gemini · {settings.gemini_model} (free tier)",
        "analisa": analisa or text,
        "verdict": verdict,
        "usage": res.get("usage") or {},
    }
