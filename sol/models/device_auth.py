"""Device authentication model — tracks known devices and PIN verification state."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from sol.models.base import Base, TimestampMixin, new_uuid


class DeviceAuth(Base, TimestampMixin):
    __tablename__ = "device_auth"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    device_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String, nullable=False, default="Unknown Device")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending | approved | blocked
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AppPin(Base, TimestampMixin):
    __tablename__ = "app_pin"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_uuid)
    pin_hash: Mapped[str] = mapped_column(String, nullable=False)
