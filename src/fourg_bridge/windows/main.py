"""Windows entry point; also supports non-mutating packaged smoke checks."""

from __future__ import annotations

import argparse
import ctypes as c
import json
import sys
import tempfile
import time
from pathlib import Path

from fourg_bridge.windows import VERSION
from fourg_bridge.windows.native import DCB, IfRow, dll


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--wait-instance", action="store_true")
    parser.add_argument("--self-test", type=Path)
    parser.add_argument("--ui-smoke", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("4G Bridge Windows 版需要 Windows 11 x64")
    kernel = dll("kernel32")
    kernel.CreateMutexW.argtypes = [c.c_void_p, c.c_int, c.c_wchar_p]
    kernel.CreateMutexW.restype = c.c_void_p
    kernel.CloseHandle.argtypes = [c.c_void_p]
    mutex = None
    if not (args.self_test or args.ui_smoke):
        for _ in range(60 if args.wait_instance else 1):
            mutex = kernel.CreateMutexW(None, False, "Local\\4GBridgeWindows")
            if c.get_last_error() != 183:
                break
            kernel.CloseHandle(mutex)
            mutex = None
            time.sleep(0.5)
        if mutex is None:
            raise SystemExit("4G Bridge 已在运行，请从系统托盘打开")
    try:
        _run(args)
    finally:
        if mutex:
            kernel.CloseHandle(mutex)


def _run(args: argparse.Namespace) -> None:
    import tkinter as tk
    from tkinter import messagebox

    from fourg_bridge.windows.runtime import Runtime
    from fourg_bridge.windows.settings import app_directory
    from fourg_bridge.windows.tray import TrayIcon
    from fourg_bridge.windows.ui import Window

    if args.self_test:
        from fourg_bridge.windows.platform import inventory

        snapshot = inventory()  # Read-only; no SMS / network operations.
        from fourg_bridge.windows.native import interface_counters

        checked = 0
        for adapter in snapshot.adapters:
            try:
                interface_counters(adapter.index)
                checked += 1
            except Exception:
                continue
        args.self_test.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "windows": True,
                    "dcb_size": c.sizeof(DCB),
                    "ifrow_size": c.sizeof(IfRow),
                    "inventory_read": True,
                    "counter_interfaces": checked,
                    "hardware_test": "not_run",
                    "mutations": 0,
                }
            ),
            encoding="utf-8",
        )
        if c.sizeof(DCB) != 28 or c.sizeof(IfRow) != 1352 or not checked:
            raise SystemExit(1)
        return
    root = tk.Tk()
    try:
        directory = (
            Path(tempfile.mkdtemp(prefix="4gbridge-ui-")) if args.ui_smoke else app_directory()
        )
        runtime = Runtime(directory)
        window = Window(root, runtime, smoke=bool(args.ui_smoke))
        icon = Path(__file__).with_name("bridge.ico")
        if icon.exists():
            root.iconbitmap(str(icon))  # type: ignore[no-untyped-call]
            try:
                window.tray = TrayIcon(root, icon, window.show, runtime.command)
            except Exception:
                window.status.set("托盘初始化失败；窗口将保留在任务栏")
        if args.ui_smoke:

            def smoke() -> None:
                for index in range(6):
                    window.tabs.select(index)
                    root.update_idletasks()
                args.ui_smoke.write_text(
                    json.dumps(
                        {
                            "version": VERSION,
                            "pages": 6,
                            "window": [root.winfo_width(), root.winfo_height()],
                            "tray": bool(window.tray and window.tray.available),
                            "hardware_test": "not_run",
                            "mutations": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                window.destroy()

            root.after(1200, smoke)
        else:
            runtime.start()
            if args.background:
                window.hide()
        root.mainloop()
    except Exception:
        messagebox.showerror(
            "4G Bridge 启动失败",
            "本地数据或系统组件不可用。未发送短信或开启数据。\n"
            "请保留本地数据文件以便诊断，不要删除流量锁定记录。",
            parent=root,
        )
        root.destroy()
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
