"""Stable, accessible menu-bar presentation, independent of AppKit."""

from dataclasses import dataclass

from fourg_bridge.models import DataState, DeviceState, ModemSnapshot


@dataclass(frozen=True, slots=True)
class StatusItemStyle:
    symbol: str
    level: float
    secondary: bool
    description: str


@dataclass(frozen=True, slots=True)
class BadgePalette:
    foreground: tuple[float, float, float]
    background: tuple[float, float, float]


def badge_palette(style: StatusItemStyle, *, dark: bool) -> BadgePalette:
    """Opaque paired colors keep the small label readable over any wallpaper."""
    if style.symbol == "exclamationmark.triangle":
        return BadgePalette((1, 1, 1), (0.53, 0.31, 0.02))
    if style.secondary:
        if dark:
            return BadgePalette((0.66, 0.82, 0.99), (0.14, 0.23, 0.34))
        return BadgePalette((0.24, 0.40, 0.60), (0.90, 0.94, 0.99))
    return BadgePalette((1, 1, 1), (0.10, 0.40, 0.78) if dark else (0.08, 0.37, 0.75))


def status_item_style(snapshot: ModemSnapshot) -> StatusItemStyle:
    if snapshot.data_state == DataState.PROTECTION_FAILED:
        return StatusItemStyle("exclamationmark.triangle", 1, False, "数据保护失败，请检查模块")
    if snapshot.device_state == DeviceState.ERROR:
        return StatusItemStyle("exclamationmark.triangle", 1, False, "模块读取异常")
    if snapshot.descriptor is None:
        return StatusItemStyle("cable.connector", 0, True, "模块未连接")
    if snapshot.data_state in (DataState.ENABLING, DataState.DISABLING):
        return StatusItemStyle("arrow.triangle.2.circlepath", 1, True, "正在切换 4G 数据")
    rssi = snapshot.rssi_dbm
    level = (
        sum(rssi >= threshold for threshold in (-110, -100, -90, -80)) / 4
        if rssi is not None
        else 0
    )
    enabled = snapshot.data_state == DataState.ON
    description = "4G 数据已开启" if enabled else "4G 数据已关闭；短信转发可通过 Wi-Fi 工作"
    if rssi is not None:
        description += f" · 信号 {rssi} dBm"
    return StatusItemStyle("cellularbars", level, not enabled, description)
