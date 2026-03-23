from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
