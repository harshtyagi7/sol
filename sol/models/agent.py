from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)  # anthropic|openai|google
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    paper_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    virtual_capital: Mapped[float] = mapped_column(default=1_000_000.0)  # 10L virtual capital
