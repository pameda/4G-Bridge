"""Stable reason codes shared by the dashboard and privacy-safe Chinese log."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    code: str
    title: str
    action: str


MESSAGES = {
    "missing": ("未发现唯一兼容模块", "检查 USB、官方驱动和设备页。"),
    "sim": ("SIM 身份未就绪", "检查 SIM 与 AT 串口；不会沿用其他卡的套餐。"),
    "registration": ("蜂窝网络尚未注册", "检查信号、SIM 状态与运营商服务。"),
    "permission": ("缺少网络控制权限", "在设置中主动选择以管理员权限重新启动。"),
    "unknown": ("等待完整套餐数据", "确认后查询一次运营商；短信可能收费。"),
    "stale": ("套餐快照已过期", "重新查询运营商；不会后台自动发送收费短信。"),
    "confirmation": ("套餐达到 80% 确认线", "确认后可继续本次连接，98% 仍会关闭。"),
    "locked": ("套餐达到 98%，已锁定", "本计费周期保持关闭；重新启动不能绕过保护。"),
    "probe_timeout": ("Wi-Fi 联网检测超时", "正在按连续失败规则判断，不会无限等待 DNS。"),
    "probe_error": ("Wi-Fi 探测暂不可用", "暂停本轮判断；检查系统网络或稍后重新检测。"),
    "address": ("正在等待模块取得地址", "正在验证网卡与路由；尚未证明互联网连通。"),
    "protection": ("数据关闭尚未确认", "检查权限和模块网卡；不要将此状态视为已关闭。"),
    "wifi": ("优先使用 Wi-Fi", "Wi-Fi 可用时不自动消耗 4G 数据。"),
    "disabled": ("自动接管未启用", "在总览主动启用自动接管。"),
    "ready": ("套餐与设备满足接管条件", "等待 Wi-Fi 状态判断。"),
}


def diagnostic(code: str) -> Diagnostic:
    title, action = MESSAGES.get(code, MESSAGES["probe_error"])
    return Diagnostic(code if code in MESSAGES else "probe_error", title, action)
