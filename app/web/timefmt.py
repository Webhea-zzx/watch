"""将库内 naive UTC 时间格式化为 UTC+8（中国常用显示）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# 固定东八区，与是否夏令时无关（中国不使用夏令时）
_UTC_PLUS_8 = timezone(timedelta(hours=8))


def format_local_time(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is not None:
        utc = dt.astimezone(timezone.utc)
    else:
        utc = dt.replace(tzinfo=timezone.utc)
    local = utc.astimezone(_UTC_PLUS_8)
    return local.strftime("%Y-%m-%d %H:%M:%S")
