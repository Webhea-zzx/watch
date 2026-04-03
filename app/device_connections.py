"""在线设备 TCP 连接注册：按 device_id 保留最新连接，供管理端主动下发少量配置。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RawMessage
from app.protocol.dispatch import OutboundSeq
from app.protocol.framing import build_frame

logger = logging.getLogger(__name__)

# 管理端允许的上报间隔（秒），与配置页选项一致；协议 UPLOAD 为「间隔秒数」
ADMIN_UPLOAD_INTERVALS_SEC = frozenset({180, 300, 600, 900, 1800, 3600, 7200, 14400})


@dataclass(slots=True)
class LiveBinding:
    writer: asyncio.StreamWriter
    seq: OutboundSeq
    conn_id: str
    vendor: str
    lock: asyncio.Lock


class ConnectionRegistry:
    __slots__ = ("_lock", "_by_device")

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_device: dict[str, LiveBinding] = {}

    async def bind(
        self,
        device_id: str,
        vendor: str,
        writer: asyncio.StreamWriter,
        seq: OutboundSeq,
        conn_id: str,
        conn_lock: asyncio.Lock,
    ) -> None:
        v = (vendor or "").strip() or "ZJ"
        async with self._lock:
            self._by_device[device_id] = LiveBinding(
                writer=writer,
                seq=seq,
                conn_id=conn_id,
                vendor=v,
                lock=conn_lock,
            )

    async def unbind_connection(self, conn_id: str) -> None:
        async with self._lock:
            to_del = [did for did, b in self._by_device.items() if b.conn_id == conn_id]
            for did in to_del:
                del self._by_device[did]

    async def is_online(self, device_id: str) -> bool:
        async with self._lock:
            b = self._by_device.get(device_id)
            if b is None:
                return False
            return not b.writer.is_closing()

    async def list_online_devices(self) -> list[dict[str, str]]:
        """当前仍有效的 TCP 绑定（按 device_id 去重，每设备一条）。"""
        async with self._lock:
            rows: list[dict[str, str]] = []
            for device_id, b in self._by_device.items():
                if b.writer.is_closing():
                    continue
                rows.append(
                    {
                        "device_id": device_id,
                        "vendor": b.vendor,
                        "connection_id": b.conn_id,
                    }
                )
            rows.sort(key=lambda x: x["device_id"])
            return rows

    async def send_location_config(
        self,
        db: AsyncSession,
        device_id: str,
        mode: int,
        interval_sec: int,
    ) -> str:
        """同一 TCP 连接内严格按顺序下发两项配置（非并行）。

        顺序固定：① 定位优先方式 → 必须 write + drain 完成后再发 ② 上报间隔。
        全程持有连接锁，避免与协议自动应答交错。
        """
        if not (0 <= mode <= 4):
            logger.warning("配置下发拒绝：定位方式参数无效 device_id=%s mode=%s", device_id, mode)
            return "定位方式选项无效"
        if interval_sec not in ADMIN_UPLOAD_INTERVALS_SEC:
            logger.warning(
                "配置下发拒绝：上报间隔参数无效 device_id=%s interval_sec=%s",
                device_id,
                interval_sec,
            )
            return "上报间隔选项无效"

        async with self._lock:
            b = self._by_device.get(device_id)

        if b is None or b.writer.is_closing():
            logger.warning("配置下发失败：设备不在线 device_id=%s", device_id)
            return "当前不在线"

        wires: list[bytes] = []
        try:
            # 与 handle_client 中 bind 一致：先 conn_lock，再在短时持有注册表锁下校验
            # 「当前 device_id 是否仍绑定到本 LiveBinding」，避免重连后向旧连接误写。
            async with b.lock:
                async with self._lock:
                    cur = self._by_device.get(device_id)
                    if cur is not b:
                        logger.warning(
                            "配置下发失败：连接已切换 device_id=%s（请重新下发）",
                            device_id,
                        )
                        return "连接已变化，请重新下发"
                    if b.writer.is_closing():
                        logger.warning("配置下发失败：写入前连接已关闭 device_id=%s", device_id)
                        return "当前不在线"

                async def send_step(payload: str) -> bytes:
                    seq_hex = b.seq.next()
                    wire = build_frame(b.vendor, device_id, seq_hex, payload)
                    b.writer.write(wire)
                    await b.writer.drain()
                    return wire

                # 第一步完成后再进入第二步，禁止并发写同一 socket
                wires.append(await send_step(f"SETDWMODE,{mode}"))
                wires.append(await send_step(f"UPLOAD,{interval_sec}"))
        except Exception:
            logger.exception(
                "配置下发 TCP 写入异常 device_id=%s mode=%s interval_sec=%s 首帧是否已发出=%s",
                device_id,
                mode,
                interval_sec,
                bool(wires),
            )
            if not wires:
                return "发送失败"
            t1 = wires[0].decode("latin-1", errors="replace")
            db.add(
                RawMessage(
                    connection_id="admin",
                    direction="out",
                    vendor=b.vendor,
                    device_id=device_id,
                    raw_frame=t1,
                    parse_ok=True,
                    error=None,
                )
            )
            try:
                await db.commit()
            except Exception:
                logger.exception(
                    "配置下发：首帧已发出但记库失败 device_id=%s",
                    device_id,
                )
                return "第一步已送达，保存记录失败"
            logger.warning(
                "配置下发：第二步失败，首帧已送达 device_id=%s mode=%s interval_sec=%s",
                device_id,
                mode,
                interval_sec,
            )
            return "第一步已送达，第二步发送失败，请重试"

        for wire in wires:
            db.add(
                RawMessage(
                    connection_id="admin",
                    direction="out",
                    vendor=b.vendor,
                    device_id=device_id,
                    raw_frame=wire.decode("latin-1", errors="replace"),
                    parse_ok=True,
                    error=None,
                )
            )
        try:
            await db.commit()
        except Exception:
            logger.exception(
                "配置下发：两帧已发出但记库失败 device_id=%s mode=%s interval_sec=%s",
                device_id,
                mode,
                interval_sec,
            )
            return "配置已送到设备，保存记录失败"
        return "已下发"


_registry = ConnectionRegistry()


def get_connection_registry() -> ConnectionRegistry:
    return _registry
