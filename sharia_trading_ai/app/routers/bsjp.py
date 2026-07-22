"""Endpoint BSJP — Beli Saat Pre-closing, Jual Pagi Hari."""

from __future__ import annotations

from fastapi import APIRouter, Query
from app.core import bsjp, bsjp_advisor

router = APIRouter(prefix="/api/bsjp", tags=["bsjp"])


@router.get("/status")
def bsjp_status():
    """Status sesi BEI saat ini dan relevansinya untuk strategi BSJP."""
    return bsjp.session_status()


@router.get("/candidates")
def bsjp_candidates(
    limit: int = Query(default=15, ge=1, le=50),
    force: bool = Query(default=False),
):
    """
    Daftar kandidat BELI BSJP (pre-closing).
    Diurutkan: sinyal kuat dulu, lalu by skor BSJP.
    """
    candidates = bsjp.scan_buy_candidates(limit=limit, force=force)
    strong = [c for c in candidates if c.get("buy_signal")]
    return {
        "ok": True,
        "total": len(candidates),
        "sinyal_kuat": len(strong),
        "sesi": bsjp.session_status(),
        "candidates": candidates,
    }


@router.get("/sell-signals")
def bsjp_sell_signals():
    """
    Kandidat JUAL pagi hari dari posisi portofolio (pre-opening).
    Kondisi: IEP_pagi > CP_kemarin → gap-up terkonfirmasi.
    """
    signals = bsjp.scan_sell_signals()
    sell_now = [s for s in signals if s.get("sell_signal")]
    return {
        "ok": True,
        "total_posisi": len(signals),
        "sinyal_jual": len(sell_now),
        "sesi": bsjp.session_status(),
        "signals": signals,
    }


@router.get("/report")
def bsjp_report(
    limit: int = Query(default=10, ge=1, le=30),
    force: bool = Query(default=False),
):
    """Laporan BSJP lengkap: status sesi + kandidat beli + sinyal jual."""
    return bsjp.build_bsjp_report(limit=limit, force=force)


@router.get("/advisor/{ticker}")
def bsjp_advisor_endpoint(ticker: str, force: bool = Query(default=False)):
    """
    Analisa berbasis aturan khusus strategi BSJP untuk 1 saham.
    Mencakup: kelayakan, risiko overnight, entry/exit konkret, warning likuiditas.
    """
    # Ambil data kandidat untuk saham ini
    candidates = bsjp.scan_buy_candidates(limit=100, force=force)
    candidate = next(
        (c for c in candidates if c["ticker"].upper() == ticker.upper()),
        {}
    )

    # Jika tidak ada di candidates, buat data minimal
    if not candidate:
        from app.core.bsjp import _get_iep, _get_closing_price, _get_volume_ratio, _bsjp_score
        from app.data import tradingview_provider
        tv_data = tradingview_provider.metrics(ticker)
        iep = _get_iep(ticker)
        cp  = _get_closing_price(ticker)
        vol = _get_volume_ratio(ticker)
        candidate = {
            "ticker": ticker.upper(),
            "iep": iep,
            "cp": cp,
            "gap_iep_cp_pct": round((iep - cp) / cp * 100, 2) if iep and cp and cp > 0 else None,
            "bsjp_score": _bsjp_score(tv_data, vol),
            "buy_signal": False,
            "rec_tv": (tv_data or {}).get("recommend_label", "NO DATA"),
            "vol_ratio_5d_20d": vol,
            "fundamental": {
                "roe": (tv_data or {}).get("roe"),
                "der": (tv_data or {}).get("der"),
                "per": (tv_data or {}).get("per"),
                "pbv": (tv_data or {}).get("pbv"),
            },
            "syariah": True,
        }

    candidate["sesi_label"] = bsjp.session_status().get("label", "—")
    return bsjp_advisor.advise_bsjp(ticker, candidate)


@router.post("/alert")
def bsjp_alert(force: bool = Query(default=False)):
    """
    Kirim ringkasan BSJP ke Telegram.
    Mencakup: sinyal beli kuat + sinyal jual pagi.
    """
    report = bsjp.build_bsjp_report(force=force)
    result = bsjp.send_bsjp_alert(report)
    return {"ok": True, "telegram": result, "ringkasan": report.get("ringkasan")}
