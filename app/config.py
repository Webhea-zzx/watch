from __future__ import annotations

import os
from pathlib import Path


def _get(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


BASE_DIR = Path(__file__).resolve().parent.parent

TCP_HOST = _get("TCP_HOST", "0.0.0.0")
TCP_PORT = int(_get("TCP_PORT", "9000"))
# 无流量多久后发 TCP keepalive 探测（秒）。设备关机/断网时往往无 FIN，依赖探测剔除半开连接；0=仅开启 SO_KEEPALIVE，不改系统默认间隔
TCP_KEEPALIVE_IDLE_SEC = int(_get("TCP_KEEPALIVE_IDLE_SEC", "120"))

WEB_HOST = _get("WEB_HOST", "127.0.0.1")
WEB_PORT = int(_get("WEB_PORT", "8000"))

DATABASE_URL = _get("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'watch.db'}")

# 未设置环境变量时的默认账号（仅用于首次生成 web_auth.json）；登录后请在网页「修改密码」中改掉
ADMIN_USER = _get("ADMIN_USER", "admin")
ADMIN_PASS = _get("ADMIN_PASS", "Watch2024")

# Session 签名密钥（生产环境务必设置固定值，否则重启后会话全部失效）
SECRET_KEY = _get("SECRET_KEY", "dev-insecure-change-me-set-env-secret-key")

# 登录凭据文件（修改密码后写入此处；首次运行从 ADMIN_USER/ADMIN_PASS 生成）
WEB_AUTH_FILE = Path(_get("WEB_AUTH_FILE", str(BASE_DIR / "data" / "web_auth.json")))

FILES_DIR = Path(_get("FILES_DIR", str(BASE_DIR / "data" / "files")))
FILES_DIR.mkdir(parents=True, exist_ok=True)

# 平台回复 LGZONE 时使用的时区（相对 UTC 的整数小时，如北京为 8）
PLATFORM_TZ_OFFSET_HOURS = int(_get("PLATFORM_TZ_OFFSET_HOURS", "8"))

# 地图服务 API Key：默认读环境变量 AMAP_KEY；可在「配置下发」页写入本地文件（优先）。见 app.web.amap_key_store.get_amap_key
