"""Explicit user-supplied general allowance, not a carrier-verified balance."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from fourg_bridge.cellular.carrier_query import CarrierUsage


def manual_usage(total_gb: str, remaining_gb: str, now: datetime) -> CarrierUsage:
    try:
        total, remaining = Decimal(total_gb), Decimal(remaining_gb)
        if (
            not total.is_finite()
            or not remaining.is_finite()
            or not Decimal("0.001") <= total <= 10000
            or not 0 <= remaining <= total
        ):
            raise ValueError
        size = int(total * 1024**3)
        left = int(remaining * 1024**3)
    except (InvalidOperation, ValueError):
        raise ValueError("请输入有效总量和剩余量；剩余量不能超过总量。") from None
    return CarrierUsage(size, size - left, now, "手动套餐 · 本机估算")
