"""Endpoint Akun RDN (cash) + ringkasan cash/aset per RDN + advice Money Management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core import accounts
from app.models.schemas import AccountIn

router = APIRouter(prefix="/api", tags=["accounts"])


@router.get("/accounts")
def list_accounts():
    """Daftar akun RDN beserta saldo cash."""
    return {"accounts": accounts.list_accounts()}


@router.post("/accounts")
def upsert_account(acc: AccountIn):
    """Set/perbarui saldo cash sebuah RDN (kunci = broker)."""
    try:
        return accounts.set_account(acc.broker, acc.cash, acc.rdn, acc.bank,
                                    acc.fee_buy_pct, acc.fee_sell_pct,
                                    gold_balance_grams=acc.gold_balance_grams,
                                    gold_avg_price=acc.gold_avg_price)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/accounts/{acc_id}")
def delete_account(acc_id: int):
    if not accounts.remove_account(acc_id):
        raise HTTPException(status_code=404, detail="akun tidak ditemukan")
    return {"ok": True, "deleted": acc_id}


@router.get("/portfolio/rdn")
def portfolio_rdn():
    """Rincian CASH & ASET per RDN + saran alokasi trading (jaga N emiten)."""
    return accounts.breakdown()
