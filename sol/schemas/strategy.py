from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from sol.schemas.trade import TradeProposalCreate


class StrategyTradeIn(TradeProposalCreate):
    """A trade inside a strategy proposal. Inherits all trade fields."""
    sequence: int = Field(default=1, ge=1, description="Execution order within the strategy")
    rationale: str = Field(description="Why this specific trade fits the strategy")


class StrategyProposal(BaseModel):
    """What an agent submits — a full strategy with all planned trades."""
    name: str = Field(description="Short strategy name, e.g. 'NIFTY50 Momentum Week 1'")
    description: str = Field(description="Full strategy description and thesis")
    rationale: str = Field(description="Why this strategy makes sense right now")
    duration_days: int = Field(default=1, ge=1, le=30, description="Expected strategy duration in trading days")
    trades: list[StrategyTradeIn] = Field(description="All planned trades in execution order")

    @property
    def max_loss_possible(self) -> float:
        """Sum of all trade risk amounts (entry - SL) * qty."""
        total = 0.0
        for t in self.trades:
            if t.entry_price and t.stop_loss:
                risk = abs(t.entry_price - t.stop_loss) * t.quantity
                total += risk
        return round(total, 2)


class StrategyApproval(BaseModel):
    """User's approval decision for a strategy."""
    max_loss_approved: float = Field(
        gt=0,
        description="Maximum rupee loss you allow before all trades are halted. Must be > 0."
    )
    note: Optional[str] = None


class StrategyTradeOut(BaseModel):
    id: str
    strategy_id: str
    symbol: str
    exchange: str
    direction: str
    order_type: str
    product_type: str
    option_type: Optional[str] = None
    sequence: int
    quantity: int
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_amount: Optional[float]
    rationale: str
    status: str
    skip_reason: Optional[str]
    kite_order_id: Optional[str]
    executed_at: Optional[datetime]
    actual_pnl: Optional[float]

    model_config = {"from_attributes": True}


class StrategyOut(BaseModel):
    id: str
    agent_id: str
    agent_name: str
    name: str
    description: str
    rationale: str
    duration_days: int
    max_loss_possible: float
    max_loss_approved: Optional[float]
    actual_loss: float
    status: str
    user_note: Optional[str]
    proposed_at: datetime
    approved_at: Optional[datetime]
    completed_at: Optional[datetime]
    is_virtual: bool
    trades: list[StrategyTradeOut] = []

    model_config = {"from_attributes": True}
