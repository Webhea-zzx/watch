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
    # 卫星定位（WGS84，与协议一致）
    last_gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_gps_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_gps_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 网络定位（国内地图常用 GCJ-02）
    last_net_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_net_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_net_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_net_radius: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_net_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 列表/详情当前展示：gps / net
    last_display_source: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # 每条定位类上报处理完后递增，用于丢弃过期的地图异步写入
    location_apply_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


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
