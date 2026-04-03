"""地图服务 API Key：优先读本页保存的本地文件，否则回退环境变量 AMAP_KEY。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.config import BASE_DIR, _get

AMAP_KEY_FILE = Path(_get("AMAP_KEY_FILE", str(BASE_DIR / "data" / "amap_key.json")))


def load_stored_amap_key() -> str:
    if not AMAP_KEY_FILE.is_file():
        return ""
    try:
        raw = AMAP_KEY_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    k = data.get("key")
    if k is None:
        return ""
    return str(k).strip()


def save_stored_amap_key(key: str) -> None:
    """写入或清空本页保存的 Key（不写环境变量）。"""
    AMAP_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    k = key.strip()
    if not k:
        try:
            AMAP_KEY_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return
    tmp = AMAP_KEY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"key": k}, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.move(str(tmp), str(AMAP_KEY_FILE))


def get_amap_key() -> str:
    """实际调用地图 REST 时使用的 Key：本页保存优先，否则环境变量。"""
    s = load_stored_amap_key()
    if s:
        return s
    return _get("AMAP_KEY", "").strip()
