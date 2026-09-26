"""Native notification-area icon and power events; no UI automation."""

from __future__ import annotations

import ctypes as c
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from fourg_bridge.windows.native import U32, Guid, dll


class NotifyIcon(c.Structure):
    _fields_: ClassVar = [
        ("size", U32),
        ("window", c.c_void_p),
        ("id", U32),
        ("flags", U32),
        ("callback", U32),
        ("icon", c.c_void_p),
        ("tip", c.c_wchar * 128),
        ("state", U32),
        ("mask", U32),
        ("info", c.c_wchar * 256),
        ("version", U32),
        ("title", c.c_wchar * 64),
        ("info_flags", U32),
        ("guid", Guid),
        ("balloon", c.c_void_p),
    ]


class TrayIcon:
    def __init__(
        self, root: Any, path: Path, show: Callable[[], None], power: Callable[[str], None]
    ) -> None:
        self.root, self.show, self.power = root, show, power
        self.user = dll("user32")
        self.shell = dll("shell32")
        self.user.GetParent.argtypes = [c.c_void_p]
        self.user.GetParent.restype = c.c_void_p
        self.user.LoadImageW.argtypes = [c.c_void_p, c.c_wchar_p, U32, c.c_int, c.c_int, U32]
        self.user.LoadImageW.restype = c.c_void_p
        self.user.DestroyIcon.argtypes = [c.c_void_p]
        self.user.RegisterWindowMessageW.argtypes = [c.c_wchar_p]
        self.restart_message = self.user.RegisterWindowMessageW("TaskbarCreated")
        self.user.SetWindowLongPtrW.argtypes = [c.c_void_p, c.c_int, c.c_void_p]
        self.user.SetWindowLongPtrW.restype = c.c_void_p
        self.user.CallWindowProcW.argtypes = [c.c_void_p, c.c_void_p, U32, c.c_size_t, c.c_ssize_t]
        self.user.CallWindowProcW.restype = c.c_ssize_t
        self.shell.Shell_NotifyIconW.argtypes = [U32, c.POINTER(NotifyIcon)]
        root.update_idletasks()
        self.window = self.user.GetParent(root.winfo_id()) or root.winfo_id()
        self.icon = self.user.LoadImageW(None, str(path), 1, 32, 32, 0x10)
        if not self.icon:
            raise OSError("icon unavailable")
        self.record = NotifyIcon()
        self.record.size = c.sizeof(NotifyIcon)
        self.record.window, self.record.id = self.window, 1
        self.record.flags = 1 | 2 | 4
        self.record.callback, self.record.icon = 0x8010, self.icon
        self.record.tip = "4G Bridge · 双击打开控制面板"
        callback = c.__dict__["WINFUNCTYPE"](c.c_ssize_t, c.c_void_p, U32, c.c_size_t, c.c_ssize_t)
        self.proc = callback(self._window_proc)
        self.previous = self.user.SetWindowLongPtrW(self.window, -4, self.proc)
        if not self.previous:
            self.user.DestroyIcon(self.icon)
            raise OSError("tray window unavailable")
        self.available = bool(self.shell.Shell_NotifyIconW(0, c.byref(self.record)))

    def _window_proc(self, window: int, message: int, wparam: int, lparam: int) -> int:
        if message == self.restart_message:
            self.shell.Shell_NotifyIconW(0, c.byref(self.record))
        elif message == 0x8010 and lparam in (0x202, 0x203, 0x205):
            self.root.after_idle(self.show)
        elif message == 0x218:  # WM_POWERBROADCAST
            if wparam == 4:
                self.power("sleep")
            elif wparam in (7, 18):
                self.power("wake")
        elif message == 0x11:  # WM_QUERYENDSESSION
            self.power("sleep")
        return int(self.user.CallWindowProcW(self.previous, window, message, wparam, lparam))

    def tooltip(self, text: str) -> None:
        self.record.tip = text[:127]
        self.shell.Shell_NotifyIconW(1, c.byref(self.record))

    def close(self) -> None:
        self.shell.Shell_NotifyIconW(2, c.byref(self.record))
        self.user.SetWindowLongPtrW(self.window, -4, self.previous)
        self.user.DestroyIcon(self.icon)
