from __future__ import annotations

from datetime import datetime


def format_relay(sender: str, timestamp: datetime, body: str) -> str:
    local_time = timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
    return f"【4G短信】\n\n来自：{sender}\n时间：{local_time}\n\n{body}"


def format_test_message() -> str:
    return "【4G Bridge】\niMessage 转发测试成功。"
