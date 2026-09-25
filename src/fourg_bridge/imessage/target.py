"""Validate routable identifiers without guessing a user's country or recipient."""

import re


class InvalidTarget(ValueError):
    pass


def normalize_target(value: str) -> str:
    target = value.strip()
    if not target or any(ord(char) < 32 for char in target):
        raise InvalidTarget("目标为空或包含控制字符。")
    if "@" in target:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", target):
            raise InvalidTarget("请输入有效的 iMessage 邮箱地址。")
        return target
    number = re.sub(r"[ ()\-]", "", target)
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", number):
        raise InvalidTarget("手机号需带国家区号，例如中国大陆号码前加 +86；不会自动更改接收人。")
    return number
