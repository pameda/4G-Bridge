"""Win32 serial and 64-bit interface counters, using the system DLLs only."""

from __future__ import annotations

import ctypes as c
import re
import sys
from typing import Any, ClassVar

from fourg_bridge.windows.platform import PlatformError

U32 = c.c_uint32
U64 = c.c_uint64
U16 = c.c_uint16
U8 = c.c_ubyte


def dll(name: str) -> Any:
    if sys.platform != "win32":
        raise PlatformError("此操作需要 Windows")
    return c.WinDLL(name, use_last_error=True)


class DCB(c.Structure):
    _fields_: ClassVar = [
        ("length", U32),
        ("baud", U32),
        ("flags", U32),
        ("reserved", U16),
        ("xonlim", U16),
        ("xofflim", U16),
        ("bytesize", U8),
        ("parity", U8),
        ("stopbits", U8),
        ("xon", c.c_char),
        ("xoff", c.c_char),
        ("error", c.c_char),
        ("eof", c.c_char),
        ("evt", c.c_char),
        ("reserved1", U16),
    ]


class SerialPort:
    def __init__(self, name: str) -> None:
        if not re.fullmatch(r"COM[1-9][0-9]{0,3}", name):
            raise ValueError("无效的串口")
        self.api = dll("kernel32")
        self.api.CreateFileW.argtypes = [c.c_wchar_p, U32, U32, c.c_void_p, U32, U32, c.c_void_p]
        self.api.CreateFileW.restype = c.c_void_p
        for method in ("GetCommState", "SetCommState", "SetCommTimeouts"):
            getattr(self.api, method).argtypes = [c.c_void_p, c.c_void_p]
        self.api.ReadFile.argtypes = [c.c_void_p, c.c_void_p, U32, c.c_void_p, c.c_void_p]
        self.api.WriteFile.argtypes = self.api.ReadFile.argtypes
        self.api.CloseHandle.argtypes = [c.c_void_p]
        self.handle = self.api.CreateFileW("\\\\.\\" + name, 0xC0000000, 0, None, 3, 0, None)
        if self.handle == c.c_void_p(-1).value:
            self.handle = None
            raise PlatformError("串口无法打开：可能被占用、设备已移除或驱动未就绪")
        try:
            state = DCB()
            state.length = c.sizeof(state)
            self._check(self.api.GetCommState(self.handle, c.byref(state)))
            state.baud, state.flags, state.bytesize, state.parity, state.stopbits = (
                115200,
                1,
                8,
                0,
                0,
            )
            self._check(self.api.SetCommState(self.handle, c.byref(state)))
            # Bounded reads allow unplug and shutdown without blocking the GUI.
            timeouts = (U32 * 5)(50, 0, 250, 0, 1000)
            self._check(self.api.SetCommTimeouts(self.handle, c.byref(timeouts)))
        except Exception:
            self.close()
            raise

    @staticmethod
    def _check(ok: int) -> None:
        if not ok:
            raise PlatformError("串口通信失败，请重新检测模块")

    def read(self, timeout_ms: int) -> bytes:
        buffer = c.create_string_buffer(65536)
        count = U32()
        self._check(self.api.ReadFile(self.handle, buffer, len(buffer), c.byref(count), None))
        return buffer.raw[: count.value]

    def write(self, data: bytes, timeout_ms: int) -> int:
        count = U32()
        buffer = c.create_string_buffer(data)
        self._check(self.api.WriteFile(self.handle, buffer, len(data), c.byref(count), None))
        if count.value != len(data):
            raise PlatformError("串口写入不完整，发送结果不确定")
        return count.value

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class Guid(c.Structure):
    _fields_: ClassVar = [("d1", U32), ("d2", U16), ("d3", U16), ("d4", U8 * 8)]


class IfRow(c.Structure):
    _fields_: ClassVar = [
        ("luid", U64),
        ("index", U32),
        ("guid", Guid),
        ("alias", U16 * 257),
        ("description", U16 * 257),
        ("address_length", U32),
        ("address", U8 * 32),
        ("permanent", U8 * 32),
        *[
            (name, U32)
            for name in ("mtu", "type", "tunnel", "media", "physical", "access", "direction")
        ],
        ("flags", U8),
        ("oper", U32),
        ("admin", U32),
        ("connect", U32),
        ("network_guid", Guid),
        ("connection", U32),
        *[
            (name, U64)
            for name in (
                "tx_speed",
                "rx_speed",
                "rx",
                "in_ucast",
                "in_nucast",
                "in_discards",
                "in_errors",
                "in_unknown",
                "in_ucast_bytes",
                "in_multicast",
                "in_broadcast",
                "tx",
                "out_ucast",
                "out_nucast",
                "out_discards",
                "out_errors",
                "out_ucast_bytes",
                "out_multicast",
                "out_broadcast",
                "out_queue",
            )
        ],
    ]


def interface_counters(index: int) -> tuple[int, int]:
    row = IfRow()
    row.index = index
    api = dll("iphlpapi")
    api.GetIfEntry2.argtypes = [c.POINTER(IfRow)]
    api.GetIfEntry2.restype = U32
    if api.GetIfEntry2(c.byref(row)):
        raise PlatformError("网卡计量不可用，暂停数据以保护流量")
    return int(row.rx), int(row.tx)


def is_admin() -> bool:
    return bool(dll("shell32").IsUserAnAdmin()) if sys.platform == "win32" else False
