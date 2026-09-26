"""Stable, accessible menu-bar presentation, independent of AppKit."""

from dataclasses import dataclass

from fourg_bridge.models import DataState, DeviceState, ModemSnapshot


@dataclass(frozen=True, slots=True)
class StatusItemStyle:
    symbol: str
    level: float
    secondary: bool
    description: str


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
