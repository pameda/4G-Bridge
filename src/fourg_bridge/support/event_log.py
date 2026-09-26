"""Bounded, memory-only Chinese event journal accepting only catalogued event codes."""

from collections import deque
from collections.abc import Mapping
from datetime import datetime
from threading import Lock

EVENTS = {
    "start": ("信息", "系统", "应用已启动"),
    "sleep": ("信息", "系统", "Mac 即将睡眠，执行数据安全关闭"),
    "wake": ("信息", "系统", "Mac 已唤醒，重新检测模块与网络"),
    "connected": ("信息", "模块", "已检测到兼容的 4G 模块"),
    "missing": ("警告", "模块", "模块未连接或暂时不可用"),
    "data_on": ("信息", "网络", "4G 数据已开启"),
    "data_off": ("信息", "网络", "4G 数据已关闭"),
    "data_transition": ("信息", "网络", "正在切换 4G 数据状态"),
    "warning": ("警告", "网络", "检测到连接或保护异常，请查看设备页"),
    "relay": ("信息", "短信", "Messages 已接受转发请求，不代表对端已送达"),
    "relay_wait": ("警告", "短信", "转发条件未就绪，请检查目标、钥匙串与服务状态"),
    "query": ("信息", "运营商", "用户已确认发送一次流量查询短信"),
    "query_end": ("信息", "运营商", "查询发送操作已结束，具体结果请查看运营商页"),
    "reply": ("信息", "运营商", "已收到本次查询的运营商回复"),
    "login": ("信息", "系统", "已请求更新登录启动，请以系统登录项状态为准"),
    "auto": ("信息", "网络", "Wi-Fi 故障，已请求自动接管；连接建立需要时间"),
    "carrier80": ("警告", "流量", "套餐估算达到 80%，已请求关闭，继续使用需要确认"),
    "carrier98": ("警告", "流量", "套餐估算达到 98% 或计量不可用，已请求保护性关闭"),
}


class EventLog:
    def __init__(self, limit: int = 500, catalog: Mapping[str, tuple[str, str, str]] = EVENTS):
        self._catalog = dict(catalog)
        self._rows: deque[tuple[str, str]] = deque(maxlen=limit)
        self._lock = Lock()

    def add(self, code: str) -> None:
        level, category, text = self._catalog[code]  # Reject arbitrary strings/private payloads.
        line = f"{datetime.now().astimezone():%m-%d %H:%M:%S}  [{level}] [{category}] {text}"
        with self._lock:
            self._rows.append((level, line))

    def text(self, warnings_only: bool = False) -> str:
        with self._lock:
            return "\n".join(
                line for level, line in self._rows if not warnings_only or level == "警告"
            )

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
