"""后台登录凭据：持久化到 data/web_auth.json，首次从环境变量 ADMIN_USER / ADMIN_PASS 初始化。"""

from __future__ import annotations

import json
import secrets
from hashlib import pbkdf2_hmac
from pathlib import Path

from app.config import ADMIN_PASS, ADMIN_USER, WEB_AUTH_FILE

_ITERATIONS = 390_000


def _hash_password(password: str, salt_hex: str) -> str:
    return pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        _ITERATIONS,
    ).hex()


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    return salt, _hash_password(password, salt)


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        calc = _hash_password(password, salt_hex)
    except ValueError:
        return False
    return secrets.compare_digest(calc, hash_hex)


def _read_store() -> dict | None:
    if not WEB_AUTH_FILE.is_file():
        return None
    try:
        data = json.loads(WEB_AUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    u, s, h = data.get("username"), data.get("salt"), data.get("hash")
    if not isinstance(u, str) or not isinstance(s, str) or not isinstance(h, str):
        return None
    return {"username": u, "salt": s, "hash": h}


def _write_store(data: dict) -> None:
    WEB_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WEB_AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(WEB_AUTH_FILE)


def ensure_auth_file() -> None:
    if WEB_AUTH_FILE.is_file():
        return
    salt, h = hash_password(ADMIN_PASS)
    _write_store({"username": ADMIN_USER, "salt": salt, "hash": h})


def get_stored_username() -> str:
    ensure_auth_file()
    data = _read_store()
    if data is None:
        return ADMIN_USER
    return data["username"]


def _username_eq(a: str, b: str) -> bool:
    ae, be = a.encode("utf-8"), b.encode("utf-8")
    if len(ae) != len(be):
        return False
    return secrets.compare_digest(ae, be)


def verify_login(username: str, password: str) -> bool:
    ensure_auth_file()
    data = _read_store()
    if data is None:
        return False
    if not _username_eq(username.strip(), data["username"]):
        return False
    return verify_password(password, data["salt"], data["hash"])


def change_password(current_password: str, new_password: str) -> tuple[bool, str]:
    ensure_auth_file()
    data = _read_store()
    if data is None:
        return False, "无法读取账户配置"
    if not verify_password(current_password, data["salt"], data["hash"]):
        return False, "当前密码不正确"
    if len(new_password) < 8:
        return False, "新密码至少 8 位"
    salt, h = hash_password(new_password)
    _write_store({"username": data["username"], "salt": salt, "hash": h})
    return True, ""
