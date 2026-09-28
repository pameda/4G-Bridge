"""Bounded, thread-safe, memory-only inbox. Never stores PDU or body on disk."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from threading import RLock

from fourg_bridge.models import AssembledSMS, RelayStatus
from fourg_bridge.support.privacy import stable_message_hash


@dataclass(frozen=True, slots=True)
class ReceivedSMS:
    message_hash: str
    sender: str = field(repr=False)
    timestamp: datetime
    body: str = field(repr=False)
    status: RelayStatus | None = None

    @property
    def can_backfill(self) -> bool:
        return self.status in (None, RelayStatus.PENDING, RelayStatus.RETRY, RelayStatus.FAILED)

    @property
    def status_label(self) -> str:
        return {
            None: "已接收 · 未转发",
            RelayStatus.PENDING: "等待转发",
            RelayStatus.SENDING: "正在提交",
            RelayStatus.RETRY: "等待重试",
            RelayStatus.SENT: "Messages 已接受",
            RelayStatus.CLEANUP_PENDING: "已接受 · 等待清理",
            RelayStatus.CLEANUP_BLOCKED: "已接受 · 清理暂停",
            RelayStatus.DELIVERY_UNKNOWN: "发送结果待核对",
            RelayStatus.FAILED: "转发失败",
        }[self.status]


class SMSInbox:
    def __init__(self, capacity: int = 200) -> None:
        if capacity < 1:
            raise ValueError("Inbox capacity must be positive")
        self._capacity = capacity
        self._identity: tuple[str | None, str | None] | None = None
        self._rows: dict[str, ReceivedSMS] = {}
        self._lock = RLock()

    @property
    def identity(self) -> tuple[str | None, str | None] | None:
        with self._lock:
            return self._identity

    def bind(self, identity: tuple[str | None, str | None]) -> None:
        """Retain across reconnects; discard another SIM/device's private content."""
        with self._lock:
            if self._identity != identity:
                self._rows.clear()
                self._identity = identity

    def add(self, message: AssembledSMS) -> None:
        key = stable_message_hash(
            message.sender, message.timestamp.isoformat(), message.ordered_pdus
        )
        with self._lock:
            if key in self._rows:
                return
            self._rows[key] = ReceivedSMS(key, message.sender, message.timestamp, message.body)
            if len(self._rows) > self._capacity:
                oldest = min(self._rows, key=lambda k: self._rows[k].timestamp)
                del self._rows[oldest]

    def set_status(self, key: str, status: RelayStatus) -> None:
        with self._lock:
            if key in self._rows:
                self._rows[key] = replace(self._rows[key], status=status)

    def snapshot(self) -> tuple[ReceivedSMS, ...]:
        with self._lock:
            return tuple(sorted(self._rows.values(), key=lambda row: row.timestamp, reverse=True))
