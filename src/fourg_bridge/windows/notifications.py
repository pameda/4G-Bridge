"""System notifications only wake a worker; no location, SSID or network mutations."""

from __future__ import annotations

import ctypes as c
import threading
import time
from collections.abc import Callable
from typing import Any

from fourg_bridge.windows.native import dll

_callback_factory = getattr(c, "WINFUNCTYPE", c.CFUNCTYPE)


class NetworkNotifications:
    def __init__(self, wake: Callable[[], None]) -> None:
        self._wake = wake
        self._lock = threading.Lock()
        self._last = float("-inf")
        self._closed = False
        self._ip_handle = c.c_void_p()
        self._wlan_handle = c.c_void_p()
        self._ip: Any = None
        self._wlan: Any = None
        self._callbacks: list[Any] = []

    def signal(self, *_args: Any) -> None:
        with self._lock:
            now = time.monotonic()
            if self._closed or now - self._last < 0.25:
                return
            self._last = now
        self._wake()

    def start(self) -> bool:
        try:
            self._ip = dll("iphlpapi")
            callback_type = _callback_factory(None, c.c_void_p, c.c_void_p, c.c_int)
            callback = callback_type(self.signal)
            self._callbacks.append(callback)
            self._ip.NotifyIpInterfaceChange.argtypes = [
                c.c_uint16,
                callback_type,
                c.c_void_p,
                c.c_ubyte,
                c.POINTER(c.c_void_p),
            ]
            self._ip.NotifyIpInterfaceChange.restype = c.c_uint32
            self._ip.CancelMibChangeNotify2.argtypes = [c.c_void_p]
            if self._ip.NotifyIpInterfaceChange(0, callback, None, 0, c.byref(self._ip_handle)):
                self._ip_handle = c.c_void_p()
        except (OSError, AttributeError):
            self._ip_handle = c.c_void_p()
        try:
            self._wlan = dll("wlanapi")
            self._wlan.WlanOpenHandle.argtypes = [
                c.c_uint32,
                c.c_void_p,
                c.POINTER(c.c_uint32),
                c.POINTER(c.c_void_p),
            ]
            self._wlan.WlanCloseHandle.argtypes = [c.c_void_p, c.c_void_p]
            version = c.c_uint32()
            if self._wlan.WlanOpenHandle(2, None, c.byref(version), c.byref(self._wlan_handle)):
                self._wlan_handle = c.c_void_p()
            if self._wlan_handle:
                callback_type = _callback_factory(None, c.c_void_p, c.c_void_p)
                callback = callback_type(self.signal)
                self._callbacks.append(callback)
                self._wlan.WlanRegisterNotification.argtypes = [
                    c.c_void_p,
                    c.c_uint32,
                    c.c_int,
                    c.c_void_p,
                    c.c_void_p,
                    c.c_void_p,
                    c.c_void_p,
                ]
                # ACM only. Never request ALL/MSM, location access or scan network names.
                if self._wlan.WlanRegisterNotification(
                    self._wlan_handle, 8, 1, callback, None, None, None
                ):
                    self._wlan.WlanCloseHandle(self._wlan_handle, None)
                    self._wlan_handle = c.c_void_p()
        except (OSError, AttributeError):
            if self._wlan_handle and self._wlan:
                self._wlan.WlanCloseHandle(self._wlan_handle, None)
                self._wlan_handle = c.c_void_p()
        return bool(self._ip_handle or self._wlan_handle)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        # Not called from a callback, and no callback lock is held during unregister.
        if self._ip_handle:
            self._ip.CancelMibChangeNotify2(self._ip_handle)
            self._ip_handle = c.c_void_p()
        if self._wlan_handle:
            self._wlan.WlanRegisterNotification(self._wlan_handle, 0, 1, None, None, None, None)
            self._wlan.WlanCloseHandle(self._wlan_handle, None)
            self._wlan_handle = c.c_void_p()
