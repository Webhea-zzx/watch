from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import FILES_DIR
from app.db.models import CommandEvent, Device, RawMessage
from app.web.auth_deps import require_admin
from app.web.deps import get_db
from app.tcp_server import active_connection_count

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/stats", dependencies=[Depends(require_admin)])
async def api_stats(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    since = datetime.utcnow() - timedelta(hours=1)
    n_msg = await db.scalar(select(func.count()).select_from(RawMessage).where(RawMessage.created_at >= since))
    n_dev = await db.scalar(select(func.count()).select_from(Device))
    online = await active_connection_count()
    return JSONResponse(
        {
            "online_connections": online,
            "devices": n_dev or 0,
            "messages_last_hour": n_msg or 0,
        }
    )


@router.get("/api/events/recent", dependencies=[Depends(require_admin)])
async def api_events_recent(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    after_id: int = Query(0, ge=0),
) -> JSONResponse:
    q = (
        select(RawMessage)
        .where(RawMessage.id > after_id)
        .order_by(RawMessage.id.desc())
        .limit(limit)
    )
    r = await db.execute(q)
    rows = list(r.scalars())
    data = [
        {
            "id": m.id,
            "created_at": m.created_at.isoformat(),
            "direction": m.direction,
            "device_id": m.device_id,
            "vendor": m.vendor,
            "parse_ok": m.parse_ok,
            "snippet": (m.raw_frame[:120] + "…") if len(m.raw_frame) > 120 else m.raw_frame,
        }
        for m in reversed(rows)
    ]
    return JSONResponse({"items": data})


@router.get("/api/device/{device_id}/events", dependencies=[Depends(require_admin)])
async def api_device_events(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> JSONResponse:
    q = (
        select(CommandEvent)
        .where(CommandEvent.device_id == device_id)
        .order_by(CommandEvent.id.desc())
        .limit(limit)
    )
    r = await db.execute(q)
    items = []
    for ev in r.scalars():
        try:
            summary = json.loads(ev.summary_json) if ev.summary_json else {}
        except json.JSONDecodeError:
            summary = {}
        items.append(
            {
                "id": ev.id,
                "created_at": ev.created_at.isoformat(),
                "command": ev.command,
                "seq": ev.seq,
                "summary": summary,
                "media_path": ev.media_path,
            }
        )
    return JSONResponse({"items": items})


@router.get("/media/{name}", dependencies=[Depends(require_admin)])
async def download_media(name: str) -> FileResponse:
    safe = Path(name).name
    path = FILES_DIR / safe
    if not path.is_file():
        raise HTTPException(404)
    base = FILES_DIR.resolve()
    rp = path.resolve()
    try:
        sub = rp.is_relative_to(base)
    except AttributeError:
        sub = str(rp).startswith(str(base) + "/") or rp == base
    if not sub:
        raise HTTPException(404)
    return FileResponse(path)
