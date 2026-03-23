from __future__ import annotations

import os
from pathlib import Path


def _get(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


BASE_DIR = Path(__file__).resolve().parent.parent

TCP_HOST = _get("TCP_HOST", "0.0.0.0")
TCP_PORT = int(_get("TCP_PORT", "9000"))

WEB_HOST = _get("WEB_HOST", "127.0.0.1")
WEB_PORT = int(_get("WEB_PORT", "8000"))

DATABASE_URL = _get("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'watch.db'}")

ADMIN_USER = _get("ADMIN_USER", "admin")
ADMIN_PASS = _get("ADMIN_PASS", "change-me")

FILES_DIR = Path(_get("FILES_DIR", str(BASE_DIR / "data" / "files")))
FILES_DIR.mkdir(parents=True, exist_ok=True)

# 平台回复 LGZONE 时使用的时区（相对 UTC 的整数小时，如北京为 8）
PLATFORM_TZ_OFFSET_HOURS = int(_get("PLATFORM_TZ_OFFSET_HOURS", "8"))
