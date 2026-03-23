"""Session 鉴权：未登录时 HTML 重定向登录页，API 返回 401，HTMX 请求带 HX-Redirect。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException, Request, status


def require_admin(request: Request) -> None:
    if request.session.get("admin_ok") is True:
        return
    path = request.url.path
    if path.startswith("/api/"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    if request.headers.get("HX-Request"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"HX-Redirect": "/login"},
        )
    nxt = quote(path)
    raise HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": f"/login?next={nxt}"},
    )
