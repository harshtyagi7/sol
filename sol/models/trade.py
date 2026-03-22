from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class TradeProposal(Base, TimestampMixin):
    __tablename__ = "trade_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. RELIANCE
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)  # NSE|BSE
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY|SELL
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)  # MARKET|LIMIT|SL
    product_type: Mapped[str] = mapped_column(String(20), default="MIS")  # MIS|CNC|NRML
    option_type: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # CE|PE|FUT|None

    quantity: Mapped[int] = mapped_column(nullable=False)
    entry_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    risk_amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    risk_pct: Mapped[Optional[float]] = mapped_column(Numeric(5, 2), nullable=True)

    # PENDING | APPROVED | REJECTED | MODIFIED | EXECUTED | CANCELLED | FAILED
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    user_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_violations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list

    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    kite_order_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_virtual: Mapped[bool] = mapped_column(default=False, nullable=False)
