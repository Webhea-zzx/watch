from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import TCP_HOST, TCP_PORT
from app.db.models import CommandEvent, Device, RawMessage
from app.db.session import init_db
from app.tcp_server import active_connection_count, handle_client
from app.web.deps import get_db
from app.web.humanize import summarize_raw_frame, summary_from_parsed
from app.web.routes import router as api_router, require_admin

TEMPLATES_DIR = Path(__file__).resolve().parent / "web" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["human_frame"] = summarize_raw_frame
templates.env.globals["human_summary"] = summary_from_parsed


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    srv = await asyncio.start_server(handle_client, TCP_HOST, TCP_PORT)

    async def _serve() -> None:
        async with srv:
            await srv.serve_forever()

    task = asyncio.create_task(_serve())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="手表数据后台", lifespan=lifespan)
app.include_router(api_router)


@app.get("/partials/recent", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def partial_recent(request: Request, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RawMessage).order_by(RawMessage.id.desc()).limit(40))
    rows = list(r.scalars())
    return templates.TemplateResponse(request, "_recent.html", {"rows": rows})


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def page_index(request: Request, db: AsyncSession = Depends(get_db)):
    since = datetime.utcnow() - timedelta(hours=1)
    n_msg = await db.scalar(select(func.count()).select_from(RawMessage).where(RawMessage.created_at >= since))
    n_dev = await db.scalar(select(func.count()).select_from(Device))
    online = await active_connection_count()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "online": online,
            "devices": n_dev or 0,
            "messages_last_hour": n_msg or 0,
        },
    )


@app.get("/devices", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def page_devices(request: Request, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Device).order_by(Device.last_seen.desc()))
    devs = list(r.scalars())
    return templates.TemplateResponse(request, "devices.html", {"devices": devs})


@app.get("/devices/{device_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def page_device_detail(
    request: Request,
    device_id: str,
    db: AsyncSession = Depends(get_db),
    cmd: str | None = Query(None, description="按指令名筛选"),
):
    dr = await db.execute(select(Device).where(Device.device_id == device_id))
    dev = dr.scalar_one_or_none()
    if dev is None:
        raise HTTPException(404)
    if cmd is not None:
        cmd = cmd.strip() or None
    if cmd:
        q = (
            select(CommandEvent)
            .where(
                CommandEvent.device_id == device_id,
                CommandEvent.command == cmd.upper(),
            )
            .order_by(CommandEvent.id.desc())
            .limit(200)
        )
    else:
        q = (
            select(CommandEvent)
            .where(CommandEvent.device_id == device_id)
            .order_by(CommandEvent.id.desc())
            .limit(200)
        )
    r = await db.execute(q)
    events = list(r.scalars())
    parsed_events = []
    for ev in events:
        try:
            sj = json.loads(ev.summary_json) if ev.summary_json else {}
        except json.JSONDecodeError:
            sj = {}
        media_name = Path(ev.media_path).name if ev.media_path else None
        parsed_events.append((ev, sj, media_name))
    return templates.TemplateResponse(
        request,
        "device_detail.html",
        {
            "device": dev,
            "parsed_events": parsed_events,
            "filter_cmd": cmd or "",
            "lat": dev.last_lat,
            "lng": dev.last_lng,
        },
    )


@app.get("/messages/{msg_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def page_message(request: Request, msg_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RawMessage).where(RawMessage.id == msg_id))
    m = r.scalar_one_or_none()
    if m is None:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "message_detail.html", {"m": m})
