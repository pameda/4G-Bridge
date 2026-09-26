"""In-memory TCP EStats summary. No packets, payloads, DNS or address history."""

from __future__ import annotations

import ctypes as c
import ntpath
import time
from dataclasses import dataclass
from typing import ClassVar

from fourg_bridge.windows.native import U8, U32, U64, dll, is_admin


class TcpRow(c.Structure):
    _fields_: ClassVar = [(name, U32) for name in ("state", "local", "lport", "remote", "rport")]


class OwnerRow(c.Structure):
    _fields_: ClassVar = [("row", TcpRow), ("pid", U32)]


class DataStats(c.Structure):
    _fields_: ClassVar = [
        *[
            (name, U64)
            for name in ("tx", "tx_segments", "rx", "rx_segments", "segs_out", "segs_in")
        ],
        *[(name, U32) for name in ("errors", "reason", "una", "nxt", "maximum")],
        ("acked", U64),
        ("receive_next", U32),
        ("received", U64),
    ]


@dataclass(frozen=True)
class AppRow:
    name: str
    download: float
    upload: float
    total: int


class Aggregator:
    def __init__(self) -> None:
        self.previous: dict[bytes, tuple[float, int, int]] = {}
        self.totals: dict[str, int] = {}

    def sample(self, values: list[tuple[bytes, str, int, int]], now: float) -> list[AppRow]:
        latest = {}
        grouped: dict[str, tuple[float, float]] = {}
        for key, name, rx, tx in values:
            old = self.previous.get(key)
            dr = dt = 0
            elapsed = 1.0
            if old and 0 < now - old[0] <= 10:
                elapsed = now - old[0]
                dr, dt = max(0, rx - old[1]), max(0, tx - old[2])
            latest[key] = (now, rx, tx)
            self.totals[name] = self.totals.get(name, 0) + dr + dt
            before = grouped.get(name, (0.0, 0.0))
            grouped[name] = (before[0] + dr / elapsed, before[1] + dt / elapsed)
        self.previous = latest
        # Bounded process-name history, dropped on app restart.
        if len(self.totals) > 500:
            self.totals = {name: self.totals[name] for name in grouped}
        return sorted(
            (AppRow(name, down, up, self.totals[name]) for name, (down, up) in grouped.items()),
            key=lambda row: row.download + row.upload,
            reverse=True,
        )


class AppMonitor:
    def __init__(self) -> None:
        self.api = dll("iphlpapi")
        self.api.GetExtendedTcpTable.argtypes = [c.c_void_p, c.c_void_p, c.c_int, U32, U32, U32]
        self.api.GetExtendedTcpTable.restype = U32
        self.api.GetPerTcpConnectionEStats.argtypes = [
            c.POINTER(TcpRow),
            c.c_int,
            c.c_void_p,
            U32,
            U32,
            c.c_void_p,
            U32,
            U32,
            c.c_void_p,
            U32,
            U32,
        ]
        self.api.SetPerTcpConnectionEStats.argtypes = [
            c.POINTER(TcpRow),
            c.c_int,
            c.c_void_p,
            U32,
            U32,
            U32,
        ]
        self.aggregate = Aggregator()

    @staticmethod
    def _process(pid: int) -> tuple[str, bytes]:
        kernel = dll("kernel32")
        kernel.OpenProcess.argtypes = [U32, c.c_int, U32]
        kernel.OpenProcess.restype = c.c_void_p
        kernel.CloseHandle.argtypes = [c.c_void_p]
        kernel.QueryFullProcessImageNameW.argtypes = [c.c_void_p, U32, c.c_wchar_p, c.c_void_p]
        kernel.GetProcessTimes.argtypes = [c.c_void_p] * 5
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return f"进程 {pid}", str(pid).encode("ascii")
        try:
            buffer = c.create_unicode_buffer(32768)
            size = U32(len(buffer))
            times = (U64 * 4)()
            kernel.GetProcessTimes(handle, *(c.byref(times, i * 8) for i in range(4)))
            identity = f"{pid}:{times[0]}".encode("ascii")
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, c.byref(size)):
                return ntpath.basename(buffer.value), identity
            return f"进程 {pid}", identity
        finally:
            kernel.CloseHandle(handle)

    def sample(self) -> tuple[list[AppRow], str]:
        if not is_admin():
            return [], "需要管理员权限。不会把无法取得的统计显示为 0。"
        size = U32()
        self.api.GetExtendedTcpTable(None, c.byref(size), False, 2, 5, 0)
        if not 4 <= size.value <= 16 * 1024 * 1024:
            return [], "TCP 统计不可用"
        buffer = c.create_string_buffer(size.value)
        if self.api.GetExtendedTcpTable(buffer, c.byref(size), False, 2, 5, 0):
            return [], "TCP 连接变化，请稍候"
        count = U32.from_buffer_copy(buffer.raw[:4]).value
        if 4 + count * c.sizeof(OwnerRow) > len(buffer):
            return [], "TCP 数据结构不兼容"
        values = []
        names: dict[int, tuple[str, bytes]] = {}
        for index in range(min(count, 2000)):
            owner = OwnerRow.from_buffer_copy(buffer, 4 + index * c.sizeof(OwnerRow))
            if owner.row.state != 5:
                continue
            enabled, stats = U8(), DataStats()
            row = c.byref(owner.row)
            result = self.api.GetPerTcpConnectionEStats(
                row, 1, c.byref(enabled), 0, 1, None, 0, 0, c.byref(stats), 0, c.sizeof(stats)
            )
            if result:
                continue
            if not enabled.value:
                # Enable byte counters only; no packet tracing / ETW payload capture.
                enabled.value = 1
                self.api.SetPerTcpConnectionEStats(row, 1, c.byref(enabled), 0, 1, 0)
                continue
            if owner.pid not in names:
                names[owner.pid] = self._process(owner.pid)
            name, identity = names[owner.pid]
            values.append((bytes(owner.row) + identity, name, int(stats.rx), int(stats.tx)))
        rows = self.aggregate.sample(values, time.monotonic())
        return rows, (
            "仅 IPv4 TCP；不含 UDP／QUIC／IPv6，短连接可能漏采。代理／回环可能重复计量。"
            if rows
            else "等待可用的 IPv4 TCP 采样；空列表不表示没有网络流量。"
        )
