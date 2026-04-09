from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_URL
from app.db.models import Base


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite+aiosqlite:///"):
        path = url.removeprefix("sqlite+aiosqlite:///")
        if path and not path.startswith(":"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(DATABASE_URL)


def _sqlite_connect_args() -> dict:
    """减轻 TCP 与 Web 同时写库时的「database is locked」。"""
    if "sqlite" in DATABASE_URL:
        return {"timeout": 60.0}
    return {}


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args=_sqlite_connect_args(),
)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragma(dbapi_connection, connection_record) -> None:
    if "sqlite" not in DATABASE_URL:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=60000")
    cursor.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _migrate_devices_columns(connection) -> None:
    """SQLite 已有库补列；PostgreSQL 等新库由 create_all 建全表。"""
    if "sqlite" not in DATABASE_URL:
        return
    try:
        cols = {c["name"] for c in inspect(connection).get_columns("devices")}
    except Exception:
        return
    alters: list[tuple[str, str]] = [
        ("last_gps_lat", "FLOAT"),
        ("last_gps_lng", "FLOAT"),
        ("last_gps_at", "DATETIME"),
        ("last_gps_address", "TEXT"),
        ("last_net_lat", "FLOAT"),
        ("last_net_lng", "FLOAT"),
        ("last_net_at", "DATETIME"),
        ("last_net_radius", "INTEGER"),
        ("last_net_address", "TEXT"),
        ("last_display_source", "VARCHAR(8)"),
        ("location_apply_seq", "INTEGER DEFAULT 0"),
    ]
    for name, typ in alters:
        if name not in cols:
            connection.execute(text(f"ALTER TABLE devices ADD COLUMN {name} {typ}"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_devices_columns)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return SessionLocal
