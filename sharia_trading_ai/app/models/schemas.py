"""Skema request/response (Pydantic) untuk endpoint Money Management & Plan."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class MoneyMgmtRequest(BaseModel):
    idle_money: float = Field(..., gt=0, description="Modal / idle money (IDR)")
    num_stocks: int = Field(1, ge=1, le=20, description="Jumlah saham/emiten")
    risk_pct: float = Field(3.0, gt=0, le=100, description="Risk % (maks 5%)")
    profit_pct: float = Field(6.0, gt=0, le=100, description="Target profit % (min 2x risk)")


class PositionSizeRequest(BaseModel):
    modal: float = Field(..., gt=0, description="Modal untuk 1 saham (IDR)")
    market_price: float = Field(..., gt=0, description="Harga pasar saat ini (IDR)")


class TaichiRequest(BaseModel):
    modal: float = Field(..., gt=0)
    market_price: float = Field(..., gt=0)
    mode: str = Field("konservatif", pattern="^(konservatif|moderat)$")
    cl_price: Optional[float] = Field(None, gt=0, description="Harga cut loss (OB3); kosong = dari risk%")
    risk_pct: float = Field(3.0, gt=0, le=100, description="Risk % untuk OB3 (maks 5%)")
    ticker: Optional[str] = Field(None, description="Kode saham (opsional untuk fraksi tick/lot)")


class RRRRequest(BaseModel):
    buy: float = Field(..., gt=0)
    cut_loss: Optional[float] = Field(None, gt=0, description="Cut loss manual; kosong = dari risk%")
    take_profit: Optional[float] = Field(None, gt=0)
    risk_pct: float = Field(3.0, gt=0, le=100, description="Risk % (maks 5%)")
    profit_pct: float = Field(6.0, gt=0, le=100, description="Target profit % (min 2x risk)")
    target_reward_mult: int = Field(2, ge=1, le=10)
    ticker: Optional[str] = Field(None, description="Kode saham (opsional untuk fraksi tick)")


class PositionIn(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    lots: int = Field(..., gt=0, description="Jumlah lot (1 lot = 100 lembar, atau 1 lembar untuk US)")
    avg_price: float = Field(..., gt=0, description="Harga rata-rata beli")
    broker: Optional[str] = Field(None, description="Broker (Profits Anywhere)")
    type: Optional[str] = Field("trading", pattern="^(trading|investasi)$", description="Tipe portfolio: trading atau investasi")


class AccountIn(BaseModel):
    broker: str = Field(..., min_length=1, description="Broker / nama RDN (Profits Anywhere)")
    cash: float = Field(..., ge=0, description="Saldo cash tersedia di RDN (IDR / USD)")
    rdn: Optional[str] = Field(None, description="Nomor RDN")
    bank: Optional[str] = Field(None, description="Bank RDN")
    fee_buy_pct: Optional[float] = Field(None, ge=0, le=5, description="Biaya beli (%) RDN ini")
    fee_sell_pct: Optional[float] = Field(None, ge=0, le=5, description="Biaya jual (%) RDN ini")
    gold_balance_grams: Optional[float] = Field(None, ge=0, description="Saldo emas digital (gram)")
    gold_avg_price: Optional[float] = Field(None, ge=0, description="Harga beli rata-rata emas (Rp/g)")
    currency: Optional[str] = Field("IDR", pattern="^(IDR|USD)$", description="Mata uang cash: IDR atau USD")


class HolidayIn(BaseModel):
    date: str = Field(..., description="Tanggal libur bursa (YYYY-MM-DD)")
    name: str = Field(..., min_length=1, description="Nama hari libur")


class DividendIn(BaseModel):
    ticker: str = Field(..., min_length=1, description="Kode saham")
    ex_date: str = Field(..., description="Tanggal ex-dividend / cum-date (YYYY-MM-DD)")
    amount: float = Field(..., gt=0, description="Dividen per lembar (Rp)")
    rups_date: Optional[str] = Field(None, description="Tanggal RUPS (opsional)")


class TelegramSendIn(BaseModel):
    text: Optional[str] = Field(None, description="Teks bebas; kosong = kirim ringkasan alert")

