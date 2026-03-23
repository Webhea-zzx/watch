from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
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
    cursor.execute("PRAGMA busy_timeout=60000")
    cursor.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return SessionLocal
