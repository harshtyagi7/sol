from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TradeProposalCreate(BaseModel):
    """Used by agents to submit proposals."""
    symbol: str
    exchange: Literal["NSE", "BSE", "NFO"] = "NSE"
    direction: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "SL"] = "MARKET"
    product_type: Literal["MIS", "CNC", "NRML"] = "MIS"
    option_type: Optional[Literal["CE", "PE", "FUT"]] = None  # None for equity
    quantity: int = Field(gt=0)
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    rationale: str


class RiskReport(BaseModel):
    approved: bool
    violations: list[str] = []
    risk_amount: float = 0.0
    risk_pct: float = 0.0
    modified_quantity: Optional[int] = None
    message: str = ""


class TradeProposalOut(BaseModel):
    id: str
    agent_id: str
    agent_name: str
    symbol: str
    exchange: str
    direction: str
    order_type: str
    product_type: str
    option_type: Optional[str] = None
    quantity: int
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    rationale: str
    risk_amount: Optional[float]
    risk_pct: Optional[float]
    status: str
    user_note: Optional[str]
    risk_violations: Optional[str]
    proposed_at: datetime
    reviewed_at: Optional[datetime]
    executed_at: Optional[datetime]
    kite_order_id: Optional[str]
    is_virtual: bool

    model_config = {"from_attributes": True}


class TradeReviewAction(BaseModel):
    action: Literal["approve", "reject", "modify"]
    note: Optional[str] = None
    # For modify action:
    quantity: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    entry_price: Optional[float] = None
