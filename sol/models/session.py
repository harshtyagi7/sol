from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class KiteSession(Base, TimestampMixin):
    __tablename__ = "kite_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    access_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user|assistant|system
    content: Mapped[str] = mapped_column(Text, nullable=False)
