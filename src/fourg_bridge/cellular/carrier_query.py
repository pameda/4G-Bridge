"""Explicit, single-shot carrier SMS query; never retries an uncertain submission."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from fourg_bridge.models import ATResponse


class QueryTransport(Protocol):
    def transact(
        self, command: str, payload: bytes | None = None, timeout: float = 5
    ) -> ATResponse: ...


@dataclass(frozen=True, slots=True)
class Allowance:
    remaining_bytes: int
    timestamp: datetime
    sender: str
    amount: str
    unit: str


@dataclass(frozen=True, slots=True)
class CarrierUsage:
    total_bytes: int
    used_bytes: int
    timestamp: datetime
    basis: str = "运营商套餐"

    @property
    def fraction(self) -> float:
        return self.used_bytes / self.total_bytes


def query_response_issue(body: str) -> str:
    """A redirect is not a balance. Return fixed safe UI text, never SMS content."""
    if (
        "查询" in body
        and ("APP" in body.upper() or "客户端" in body)
        and re.search(r"https?://", body, re.I)
    ):
        return "运营商只返回 App 查询入口，没有套餐数值；请在运营商 App 核实，4G 保护暂不放行。"
    return "运营商回复未包含可确认的通用套餐总量和用量；请核实指令或套餐类型。"


def parse_usage(sender: str, body: str, timestamp: datetime) -> CarrierUsage | None:
    """Only a single explicit total/used pair; never combine overlapping packages."""
    if sender not in ("10001", "10086", "10010"):
        return None
    buckets = parse_telecom_buckets(sender, body, timestamp)
    if buckets:
        return buckets
    if "流量" not in body or any(
        word in body for word in ("定向", "夜间", "闲时", "共享", "结转", "加油包", "省内")
    ):
        return None
    quantity = r"[为：:\s]*([0-9]+(?:\.[0-9]+)?)\s*(GB|MB|KB|G|M|K)(?![A-Za-z])"
    totals = re.findall(
        r"(?:流量总量|总流量|流量总额|总量|(?:国内|通用|套餐内)?流量共)" + quantity, body, re.I
    )
    used = re.findall(r"(?:已使用(?:流量)?|已用(?:流量)?|使用流量|流量已用)" + quantity, body, re.I)
    remaining_values = re.findall(
        r"(?:剩余(?:通用|国内)?流量|(?:通用|国内)?流量剩余|剩余量|剩余)" + quantity,
        body,
        re.I,
    )
    if len(totals) != 1 or len(used) > 1 or len(remaining_values) > 1:
        return None
    if not used and not remaining_values:
        return None

    def count(value: tuple[str, str]) -> int:
        amount, unit = value
        return int(Decimal(amount) * {"K": 1024, "M": 1024**2, "G": 1024**3}[unit[0].upper()])

    total = count(totals[0])
    consumed = count(used[0]) if used else total - count(remaining_values[0])
    if total <= 0 or not 0 <= consumed <= total:
        return None
    if remaining_values and abs(total - consumed - count(remaining_values[0])) > max(
        1024**2, total * 0.001
    ):
        return None
    return CarrierUsage(total, consumed, timestamp)


def parse_telecom_buckets(sender: str, body: str, timestamp: datetime) -> CarrierUsage | None:
    """Sum only explicit domestic-general data line items, including carryover."""
    if sender != "10001" or "国内通用流量" not in body:
        return None
    section = body.split("国内通用流量", 1)[1].split("国内定向流量", 1)[0]
    quantity = r"([0-9]+(?:\.[0-9]+)?)\s*(GB|MB|KB|G|M|K)"
    records = re.findall(
        r"业务类型[：:]\s*手机上网国内流量[，,]\s*总量[：:]\s*"
        + quantity
        + r"[，,]\s*剩余量[：:]\s*"
        + quantity,
        section,
        re.I,
    )
    if not records or len(records) != section.count("业务类型：手机上网国内流量"):
        return None
    total = remaining = 0
    for amount, unit, rest, rest_unit in records:
        size = int(Decimal(amount) * {"K": 1024, "M": 1024**2, "G": 1024**3}[unit[0].upper()])
        left = int(Decimal(rest) * {"K": 1024, "M": 1024**2, "G": 1024**3}[rest_unit[0].upper()])
        if left > size:
            return None
        total += size
        remaining += left
    return (
        CarrierUsage(total, total - remaining, timestamp, "国内通用流量 · 含结转")
        if total
        else None
    )


def query_pdu(number: str, command: str) -> tuple[str, int]:
    if number not in ("10001", "10086", "10010"):
        raise ValueError("仅支持运营商服务号 10001 / 10086 / 10010")
    if not re.fullmatch(r"[A-Za-z0-9]{1,16}", command):
        raise ValueError("查询指令限 1–16 个英文字母或数字，请核实运营商指令")
    digits = number + ("F" if len(number) % 2 else "")
    swapped = "".join(digits[i + 1] + digits[i] for i in range(0, len(digits), 2))
    body = command.encode("utf-16-be")
    # SMS-SUBMIT, relative validity omitted, UCS-2, use the SIM's default SMSC.
    tpdu = (
        bytes([1, 0, len(number), 0x81]) + bytes.fromhex(swapped) + bytes([0, 8, len(body)]) + body
    )
    return "00" + tpdu.hex().upper(), len(tpdu)


def send_query(transport: QueryTransport, number: str, command: str, *, confirmed: bool) -> str:
    if not confirmed:
        raise ValueError("需要确认发送查询短信")
    pdu, length = query_pdu(number, command)
    if not transport.transact("AT+CMGF=0").ok:
        return "无法设置 PDU 模式，未发送查询。"
    try:
        response = transport.transact(f"AT+CMGS={length}", payload=pdu.encode("ascii"), timeout=30)
    except Exception:
        return "发送结果不确定，请等待运营商回复，不要立即重复查询。"
    if response.ok and any(line.startswith("+CMGS:") for line in response.lines):
        return "模块已接受查询短信，正在等待运营商回复；不代表运营商已送达。"
    return "模块未确认查询发送，请核对 SIM 短信服务；不自动重试。"


def parse_allowance(sender: str, body: str, timestamp: datetime) -> Allowance | None:
    if sender not in ("10001", "10086", "10010"):
        return None
    buckets = parse_telecom_buckets(sender, body, timestamp)
    if buckets:
        remaining = buckets.total_bytes - buckets.used_bytes
        return Allowance(remaining, timestamp, sender, f"{remaining / 1024**3:.2f}", "GB")
    usage = parse_usage(sender, body, timestamp)
    if usage:
        remaining = usage.total_bytes - usage.used_bytes
        return Allowance(remaining, timestamp, sender, f"{remaining / 1024**3:.2f}", "GB")
    matches = re.findall(
        r"(?:剩余(?:通用|国内)?流量|(?:通用|国内)?流量剩余)[为：:\s]*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(GB|MB|KB)",
        body,
        re.IGNORECASE,
    )
    if len(matches) != 1:
        return None  # Multiple packages are ambiguous; never sum overlapping allowances.
    number, unit = matches[0]
    value = int(Decimal(number) * {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[unit.upper()])
    return Allowance(value, timestamp, sender, number, unit.upper())
