from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class Position(Base, TimestampMixin):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    proposal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_virtual: Mapped[bool] = mapped_column(default=False, nullable=False)

    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # BUY|SELL
    product_type: Mapped[str] = mapped_column(String(20), default="MIS")  # MIS|CNC|NRML
    option_type: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # CE|PE|FUT|None

    quantity: Mapped[int] = mapped_column(nullable=False)
    avg_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    current_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    # OPEN | CLOSED | SL_HIT | TP_HIT | SQUAREDOFF | EXPIRED
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)

    @property
    def unrealized_pnl(self) -> float:
        if self.current_price is None:
            return 0.0
        multiplier = 1 if self.direction == "BUY" else -1
        return multiplier * (self.current_price - self.avg_price) * self.quantity
