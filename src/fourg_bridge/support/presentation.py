"""Side-effect-free display models shared by the menu and native dashboard."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from fourg_bridge.models import DataState, ModemSnapshot, TrafficSnapshot


@dataclass(frozen=True)
class UsageStyle:
    percent: str
    color: str
    title: str
    stage: int | None


def usage_style(fraction: float | None) -> UsageStyle:
    """Visual warnings only; never grants data consent or changes quota state."""
    if fraction is None or not math.isfinite(fraction) or fraction < 0:
        return UsageStyle("—", "secondary", "等待套餐数据", None)
    # Truncate rather than round across an 80%/98% policy boundary.
    percent = f"{math.floor(fraction * 1000) / 10:.1f}%"
    if fraction >= 0.98:
        return UsageStyle(percent, "red", "已达到 98% 停用线", 2)
    if fraction >= 0.8:
        return UsageStyle(percent, "red", "已达到 80% 确认线", 1)
    if fraction >= 0.75:
        return UsageStyle(percent, "red", "即将达到 80% · 提前预警", 0)
    if fraction >= 0.6:
        return UsageStyle(percent, "orange", "留意用量 · 提醒线为 80%", 0)
    return UsageStyle(percent, "blue", "当前低于 80% 提醒线", 0)


def format_bytes(value: float | int) -> str:
    amount = float(value)
    if not math.isfinite(amount) or amount < 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.0f} {unit}" if amount == 0 else f"{amount:.1f} {unit}"
        amount /= 1024
    return "—"  # pragma: no cover


def operator_name(value: str | None) -> str:
    return {"CHN-CT": "中国电信", "CHN-UNICOM": "中国联通", "CHINA MOBILE": "中国移动"}.get(
        value or "", value or "等待识别"
    )


def connection_title(snapshot: ModemSnapshot) -> str:
    if snapshot.data_state == DataState.PROTECTION_FAILED:
        return "需要检查数据保护"
    if snapshot.warning:
        return "连接需要处理"
    if snapshot.descriptor is None:
        return "连接你的 4G 模块"
    return {
        DataState.OFF: "4G 已待命",
        DataState.ON: "4G 数据已开启",
        DataState.ENABLING: "正在建立连接…",
        DataState.DISABLING: "正在关闭数据…",
    }.get(snapshot.data_state, "正在检测模块…")


def route_description(snapshot: ModemSnapshot) -> str:
    if snapshot.vpn_active:
        return "VPN 正在管理路由 · 保留现有配置"
    if snapshot.default_interface:
        return f"系统默认接口 · {snapshot.default_interface}"
    return "尚未取得系统默认接口"


class SpeedHistory:
    """Short in-memory chart history; a gap or interface change starts a new series."""

    def __init__(self, capacity: int = 60) -> None:
        self.samples: deque[TrafficSnapshot] = deque(maxlen=capacity)

    def add(self, sample: TrafficSnapshot | None) -> None:
        if sample is None:
            self.samples.clear()
            return
        if self.samples:
            last = self.samples[-1]
            elapsed = (sample.sampled_at - last.sampled_at).total_seconds()
            if sample.interface != last.interface or elapsed > 30 or elapsed < 0:
                self.samples.clear()
            elif elapsed == 0:
                return
        self.samples.append(sample)

    def normalized(self, upload: bool = False) -> tuple[float, ...]:
        scale = max((max(s.download_bps, s.upload_bps) for s in self.samples), default=1.0)
        scale = max(1.0, scale)
        return tuple(
            max(0.0, s.upload_bps if upload else s.download_bps) / scale for s in self.samples
        )
