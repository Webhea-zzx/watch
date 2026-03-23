from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    vendor: Mapped[str] = mapped_column(String(8), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_lk_battery: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_loc_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RawMessage(Base):
    __tablename__ = "raw_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    connection_id: Mapped[str] = mapped_column(String(64), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # in / out
    vendor: Mapped[str | None] = mapped_column(String(8), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    raw_frame: Mapped[str] = mapped_column(Text)
    parse_ok: Mapped[bool] = mapped_column(default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CommandEvent(Base):
    __tablename__ = "command_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    device_id: Mapped[str] = mapped_column(String(32), index=True)
    vendor: Mapped[str] = mapped_column(String(8))
    seq: Mapped[str] = mapped_column(String(4))
    command: Mapped[str] = mapped_column(String(32), index=True)
    summary_json: Mapped[str] = mapped_column(Text)
    media_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload_hex_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
