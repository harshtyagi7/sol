from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class Strategy(Base, TimestampMixin):
    """
    A strategy groups multiple trades proposed by an agent.
    User approves the strategy once with a max-loss cap.
    All trades within execute autonomously until the cap is hit.
    """
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # Duration
    duration_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Loss tracking
    max_loss_possible: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False,
        comment="Sum of all trade SL risks — worst case if every SL is hit"
    )
    max_loss_approved: Mapped[Optional[float]] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="Cap set by user on approval — strategy halts if actual_loss >= this"
    )
    actual_loss: Mapped[float] = mapped_column(
        Numeric(12, 2), default=0.0, nullable=False,
        comment="Running realized + unrealized loss across all strategy positions"
    )

    # PENDING_APPROVAL | ACTIVE | COMPLETED | CANCELLED | MAX_LOSS_HIT | PAUSED
    status: Mapped[str] = mapped_column(String(30), default="PENDING_APPROVAL", nullable=False)

    user_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_virtual: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StrategyTrade(Base, TimestampMixin):
    """
    An individual trade within a strategy.
    Executes automatically once the parent strategy is approved.
    """
    __tablename__ = "strategy_trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    strategy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("strategies.id"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Trade details
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)   # BUY|SELL
    order_type: Mapped[str] = mapped_column(String(20), default="MARKET", nullable=False)
    product_type: Mapped[str] = mapped_column(String(20), default="MIS", nullable=False)  # MIS|CNC|NRML
    option_type: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # CE|PE|FUT|None
    sequence: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # execution order

    quantity: Mapped[int] = mapped_column(nullable=False)
    entry_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    risk_amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # PENDING | EXECUTING | EXECUTED | CANCELLED | SKIPPED | FAILED
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    skip_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    kite_order_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    position_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_pnl: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
