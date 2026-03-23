from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from app.config import SECRET_KEY, TCP_HOST, TCP_PORT
from app.db.models import CommandEvent, Device, RawMessage
from app.db.session import init_db
from app.tcp_server import active_connection_count, handle_client
from app.web.auth_deps import require_admin
from app.web import auth_store
from app.web.deps import get_db
from app.web.humanize import summarize_raw_frame, summary_from_parsed
from app.web.routes import router as api_router
from app.web.timefmt import format_local_time

TEMPLATES_DIR = Path(__file__).resolve().parent / "web" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["human_frame"] = summarize_raw_frame
templates.env.filters["local_time"] = format_local_time
templates.env.globals["human_summary"] = summary_from_parsed

# 手表详情页「当前数据」HTMX 轮询间隔（秒）
DEVICE_LIVE_POLL_SECONDS = 15


async def _live_tiles_for_device(db: AsyncSession, device_id: str) -> list[dict]:
    latest_by_cmd = (
        select(CommandEvent.command, func.max(CommandEvent.id).label("mid"))
        .where(CommandEvent.device_id == device_id)
        .group_by(CommandEvent.command)
        .subquery()
    )
    lr = await db.execute(
        select(CommandEvent)
        .join(latest_by_cmd, CommandEvent.id == latest_by_cmd.c.mid)
        .order_by(CommandEvent.created_at.desc())
    )
    live_tiles: list[dict] = []
    for ev in lr.scalars():
        try:
            sj = json.loads(ev.summary_json) if ev.summary_json else {}
        except json.JSONDecodeError:
            sj = {}
        media_name = Path(ev.media_path).name if ev.media_path else None
        live_tiles.append(
            {
                "command": ev.command,
                "summary": summary_from_parsed(ev.command, sj),
                "at": ev.created_at,
                "media_name": media_name,
            }
        )
    return live_tiles


async def _load_device_live_tiles(db: AsyncSession, device_id: str) -> tuple[Device | None, list[dict]]:
    dr = await db.execute(select(Device).where(Device.device_id == device_id))
    dev = dr.scalar_one_or_none()
    if dev is None:
        return None, []
    return dev, await _live_tiles_for_device(db, device_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    auth_store.ensure_auth_file()
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
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=14 * 24 * 3600,
    same_site="lax",
    https_only=False,
)
app.include_router(api_router)


def _safe_next(nxt: str | None) -> str:
    if not nxt or not isinstance(nxt, str):
        return "/"
    nxt = nxt.strip()
    if not nxt.startswith("/") or nxt.startswith("//"):
        return "/"
    return nxt


@app.get("/login", response_class=HTMLResponse)
async def page_login(request: Request, next: str | None = None):
    if request.session.get("admin_ok") is True:
        return RedirectResponse(url=_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": None, "next": _safe_next(next), "username_hint": auth_store.get_stored_username()},
    )


@app.post("/login", response_class=HTMLResponse)
async def action_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
):
    if auth_store.verify_login(username.strip(), password):
        request.session["admin_ok"] = True
        return RedirectResponse(url=_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": "用户名或密码错误",
            "next": _safe_next(next),
            "username_hint": username.strip() or auth_store.get_stored_username(),
        },
        status_code=401,
    )


@app.post("/logout")
async def action_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/account/password", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def page_change_password(request: Request):
    return templates.TemplateResponse(
        request,
        "account_password.html",
        {"error": None, "ok": None},
    )


@app.post("/account/password", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def action_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
):
    if new_password != new_password2:
        return templates.TemplateResponse(
            request,
            "account_password.html",
            {"error": "两次输入的新密码不一致", "ok": None},
            status_code=400,
        )
    ok, msg = auth_store.change_password(current_password, new_password)
    if not ok:
        return templates.TemplateResponse(
            request,
            "account_password.html",
            {"error": msg, "ok": None},
            status_code=400,
        )
    return templates.TemplateResponse(
        request,
        "account_password.html",
        {"error": None, "ok": "密码已更新，请牢记新密码。"},
    )


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

    live_tiles = await _live_tiles_for_device(db, device_id)

    return templates.TemplateResponse(
        request,
        "device_detail.html",
        {
            "device": dev,
            "parsed_events": parsed_events,
            "live_tiles": live_tiles,
            "live_poll_seconds": DEVICE_LIVE_POLL_SECONDS,
            "filter_cmd": cmd or "",
            "lat": dev.last_lat,
            "lng": dev.last_lng,
        },
    )


@app.get(
    "/devices/{device_id}/partials/live",
    response_class=HTMLResponse,
    dependencies=[Depends(require_admin)],
)
async def partial_device_live(request: Request, device_id: str, db: AsyncSession = Depends(get_db)):
    dev, live_tiles = await _load_device_live_tiles(db, device_id)
    if dev is None:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "_device_live_grid.html",
        {"device": dev, "live_tiles": live_tiles},
    )


@app.get("/messages/{msg_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def page_message(request: Request, msg_id: int, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(RawMessage).where(RawMessage.id == msg_id))
    m = r.scalar_one_or_none()
    if m is None:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "message_detail.html", {"m": m})
