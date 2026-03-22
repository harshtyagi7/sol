from sqlalchemy import Boolean, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class RiskConfig(Base, TimestampMixin):
    __tablename__ = "risk_config"

    id: Mapped[str] = mapped_column(primary_key=True, default=new_uuid)
    max_capital_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=2.0)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=5.0)
    max_open_positions: Mapped[int] = mapped_column(default=5)
    max_position_size_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=10.0)
    require_stop_loss: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
