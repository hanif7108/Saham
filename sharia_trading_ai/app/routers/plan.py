"""Endpoint Money Management & Trading Plan."""

from __future__ import annotations

from fastapi import APIRouter

from app.core import trading_plan
from app.models.schemas import (
    MoneyMgmtRequest,
    PositionSizeRequest,
    RRRRequest,
    TaichiRequest,
)

router = APIRouter(prefix="/api/plan", tags=["trading-plan"])


@router.post("/money-management")
def money_management(req: MoneyMgmtRequest):
    """Money Management (metode MM TP): Idle→Trading(50%)→Bid→Loss(risk%)/Profit(profit%)."""
    return trading_plan.money_management(req.idle_money, req.num_stocks, req.risk_pct, req.profit_pct)


@router.post("/position-size")
def position_size(req: PositionSizeRequest):
    """LOT = Modal / Market Price / 100."""
    return trading_plan.position_size(req.modal, req.market_price)


@router.post("/taichi")
def taichi(req: TaichiRequest):
    """Taichi Trading Plan — OB1/OB2/OB3; OB3 dari risk% (selaras MM)."""
    return trading_plan.taichi_plan(req.modal, req.market_price, req.mode, req.cl_price, req.risk_pct, req.ticker)


@router.post("/rrr")
def rrr(req: RRRRequest):
    """Risk Reward Ratio — CL/TP dari Risk%/Target Profit% (selaras MM)."""
    return trading_plan.risk_reward(req.buy, req.cut_loss, req.take_profit,
                                    req.risk_pct, req.profit_pct, req.target_reward_mult, req.ticker)
