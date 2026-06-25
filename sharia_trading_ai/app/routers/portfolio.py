"""Endpoint Portofolio — tracking posisi & P/L."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.core import accounts, ocr_import, portfolio, roi, vision_import
from app.models.schemas import PositionIn

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/roi")
def portfolio_roi():
    """ROI integral (realized + unrealized) vs target profit + strategi adaptif."""
    from app.core import roi as _roi
    return {**_roi.portfolio_roi(), "adaptive": _roi.adaptive_strategy(),
            "trades": _roi.list_trades(), "curve": _roi.equity_curve()}


def _guess_mime(file: UploadFile) -> str:
    ct = (file.content_type or "").lower()
    if ct in ("image/png", "image/jpeg", "image/jpg", "image/webp", "application/pdf"):
        return "image/jpeg" if ct == "image/jpg" else ct
    name = (file.filename or "").lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith((".png",)):
        return "image/png"
    if name.endswith((".webp",)):
        return "image/webp"
    return "image/jpeg"


@router.get("/import/status")
def import_status():
    """Engine ekstraksi yang tersedia: ocr (lokal, default) & gemini (LLM, opsional)."""
    return {"available": True, "default": "ocr",
            "engines": {"ocr": True, "gemini": vision_import.engine_available() == "gemini"}}


@router.post("/import")
async def import_image(file: UploadFile = File(...), save: bool = Query(False),
                       broker: str | None = Query(None), engine: str = Query("ocr")):
    """Ekstrak posisi dari screenshot/PDF. engine=ocr (lokal, default) | gemini (LLM). save=true → simpan."""
    data = await file.read()
    if len(data) > 20_000_000:
        raise HTTPException(status_code=413, detail="File terlalu besar (>20MB)")
    mime = _guess_mime(file)
    if engine == "gemini":
        result = vision_import.parse_portfolio(data, mime, broker_hint=broker)
    else:
        result = ocr_import.parse(data, mime, broker_hint=broker)

    # Riwayat transaksi (Order History) → rekonsiliasi FIFO; save=true → terapkan ke jurnal/posisi/cash
    if result.get("doc_type") == "history" and result.get("ok"):
        from app.core import history_import
        bk = result.get("broker") or broker or "Profits Anywhere"
        if save:
            result.update(history_import.apply(result["transactions"], bk))
        else:
            result.update(history_import.reconcile(result["transactions"], bk))
        return result

    if save and result.get("ok"):
        bk = result.get("broker") or broker
        if not bk and result.get("positions"):
            # Cari broker dari item pertama posisi jika tidak ada di level dokumen
            bk = result["positions"][0].get("broker")
        if not bk:
            bk = "Profits Anywhere"
        try:
            result["imported"] = portfolio.sync_broker_positions(bk, result["positions"])
        except Exception as e:
            result["error"] = f"Gagal sinkronisasi posisi: {e}"
        # Simpan otomatis cash & biaya RDN bila terdeteksi (e-statement / trade confirmation)
        acc = result.get("account")
        if acc:
            try:
                bk = acc.get("broker") or broker or "Profits Anywhere"
                if acc.get("cash") is not None:
                    result["account_saved"] = accounts.set_account(
                        bk, float(acc["cash"]), acc.get("rdn"), acc.get("bank"),
                        acc.get("fee_buy_pct"), acc.get("fee_sell_pct"),
                        cash_at_broker=acc.get("cash_broker"),
                        cash_at_rdn=acc.get("cash_rdn"))
                elif acc.get("fee_buy_pct") is not None:
                    result["account_saved"] = accounts.update_fees(
                        bk, acc.get("fee_buy_pct"), acc.get("fee_sell_pct"))
            except Exception:  # noqa: BLE001
                pass
    return result


@router.get("/investasi-info")
def get_investasi_info():
    """Mengambil informasi gabungan rekomendasi, dividen, dan portofolio investasi tahunan."""
    from app.core.decisions import INVESTASI_TICKERS
    from app.core import undervalue, dividend
    
    # Ambil data portofolio keseluruhan
    port_data = portfolio.list_positions()
    positions = [p for p in port_data["positions"] if p.get("type") == "investasi"]
    summary = port_data.get("investasi_summary", {
        "total_cost": 0, "total_modal": 0, "total_value": 0,
        "total_net_value": 0, "total_pl": 0, "total_pl_pct": 0, "jumlah_posisi": 0
    })
    
    # Ambil emiten investasi default + emiten investasi aktif di portofolio user
    tickers = set(INVESTASI_TICKERS)
    for p in positions:
        tickers.add(p["ticker"])
        
    recommendations = []
    total_expected_dividends = 0.0
    
    for tk in sorted(tickers):
        tk_upper = tk.upper()
        # Evaluasi teknikal & fundamental undervalue
        eval_data = undervalue.evaluate(tk_upper)
        # Profil dividen
        div_prof = dividend.profile(tk_upper)
        
        # Posisi kepemilikan user
        holding = next((p for p in positions if p["ticker"] == tk_upper), None)
        
        # Hitung estimasi nominal dividen untuk kepemilikan ini
        expected_dividend_idr = 0.0
        if holding and div_prof and div_prof.get("upcoming") and div_prof["upcoming"].get("expected"):
            amt = div_prof["upcoming"].get("amount") or 0
            shares = holding.get("shares") or (holding.get("lots", 0) * 100)
            expected_dividend_idr = shares * amt
            total_expected_dividends += expected_dividend_idr
            
        recommendations.append({
            "ticker": tk_upper,
            "evaluation": eval_data,
            "dividend": div_prof,
            "holding": holding,
            "expected_dividend_idr": round(expected_dividend_idr)
        })
        
    # Tambahkan proyeksi dividen ke summary
    summary["total_expected_dividends"] = round(total_expected_dividends)
    
    return {
        "positions": positions,
        "summary": summary,
        "recommendations": recommendations
    }


@router.get("")
def get_portfolio():
    """Daftar posisi + P/L live + ringkasan total."""
    return portfolio.list_positions()


@router.post("")
def add(pos: PositionIn):
    """Tambah posisi baru."""
    try:
        return portfolio.add_position(pos.ticker, pos.lots, pos.avg_price, pos.broker, type=pos.type or "trading")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sync")
def sync_portfolio(positions: list[PositionIn], broker: str | None = Query(None)):
    """Sinkronisasi posisi portofolio secara penuh untuk broker tertentu."""
    bk = broker or "Profits Anywhere"
    pos_dicts = [
        {
            "ticker": p.ticker,
            "lots": p.lots,
            "avg_price": p.avg_price,
            "broker": bk,
            "type": p.type or "trading",
            "importable": True
        }
        for p in positions
    ]
    try:
        imported = portfolio.sync_broker_positions(bk, pos_dicts)
        return {"ok": True, "broker": bk, "imported": imported}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



@router.post("/{pos_id}/sell")
def sell(pos_id: int, exit_price: float = Query(..., gt=0),
         lots: int | None = Query(None, gt=0)):
    """JUAL posisi (sebagian/penuh) di `exit_price`. SINKRON penuh:
    catat ROI ke jurnal → tambah hasil jual (bersih) ke cash RDN → kurangi/hapus posisi.
    `lots` kosong = jual penuh. Data ROI memberi makan strategi adaptif & equity curve."""
    pos = next((p for p in portfolio.list_positions()["positions"] if p["id"] == pos_id), None)
    if not pos:
        raise HTTPException(status_code=404, detail="posisi tidak ditemukan")
    sell_lots = min(int(lots) if lots else pos["lots"], int(pos["lots"]))
    trade = roi.record_trade(pos["ticker"], sell_lots, pos["avg_price"], exit_price,
                             broker=pos.get("broker"), context="manual_sell")
    if pos.get("broker"):
        accounts.adjust_cash(pos["broker"], trade["proceeds"])      # hasil jual bersih masuk cash
    remaining = portfolio.reduce_position(pos_id, sell_lots)
    return {"ok": True, "sold_lots": sell_lots, "remaining_lots": remaining,
            "proceeds": trade["proceeds"], "roi_pct": trade["roi_pct"],
            "broker": pos.get("broker"), "trade": trade}


@router.post("/{pos_id}/close")
def close(pos_id: int, exit_price: float = Query(..., gt=0)):
    """Alias jual penuh (kompat lama)."""
    return sell(pos_id, exit_price=exit_price, lots=None)


@router.delete("/{pos_id}")
def remove(pos_id: int):
    """Hapus posisi (tanpa catat ROI)."""
    if not portfolio.remove_position(pos_id):
        raise HTTPException(status_code=404, detail="posisi tidak ditemukan")
    return {"ok": True, "deleted": pos_id}
