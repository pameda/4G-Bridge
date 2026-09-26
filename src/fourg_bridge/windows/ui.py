"""Chinese desktop UI using standard-library Tk/ttk Windows system controls."""

from __future__ import annotations

import ctypes as c
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from fourg_bridge.support.presentation import usage_style
from fourg_bridge.windows import VERSION, native
from fourg_bridge.windows.runtime import Runtime
from fourg_bridge.windows.settings import login_enabled, set_login
from fourg_bridge.windows.tray import TrayIcon

STATE_NAMES = {
    "unknown": "请查询运营商套餐",
    "stale": "套餐快照已过期，请重新查询",
    "ready": "额度可用",
    "confirmation": "达到 80%，需要确认",
    "locked": "达到 98%，已锁定",
}


def amount(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return "—"


class Window:
    def __init__(self, root: tk.Tk, runtime: Runtime, *, smoke: bool = False) -> None:
        self.root, self.runtime, self.smoke = root, runtime, smoke
        self._busy = False
        self._ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.tray: TrayIcon | None = None
        root.title("4G Bridge")
        root.geometry("1000x780")
        root.minsize(960, 650)
        root.protocol("WM_DELETE_WINDOW", self.hide)
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        self.style = ttk.Style(root)
        self.palette = self._palette()
        self._styles()
        outer = ttk.Frame(root, padding=22)
        outer.pack(fill="both", expand=True)
        title = ttk.Frame(outer)
        title.pack(fill="x", pady=(0, 16))
        ttk.Label(title, text="4G Bridge", style="Title.TLabel").pack(side="left")
        ttk.Label(title, text="WINDOWS  ·  预览版", style="Muted.TLabel").pack(side="left", padx=14)
        ttk.Button(title, text="退出", command=self.quit).pack(side="right")
        self.status = tk.StringVar(value="正在检测设备…")
        ttk.Label(outer, textvariable=self.status, wraplength=880, style="Status.TLabel").pack(
            fill="x", pady=(0, 14)
        )
        self.tabs: Any = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.pages: list[ttk.Frame] = []
        self.page_canvases: list[tk.Canvas] = []
        for title_text in ("总览", "运营商与流量", "设备", "应用网络", "运行日志", "设置"):
            shell = ttk.Frame(self.tabs)
            canvas = tk.Canvas(shell, highlightthickness=0, background=self.palette["bg"])
            scroll = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            page = ttk.Frame(canvas, padding=20)
            item = canvas.create_window(0, 0, anchor="nw", window=page)

            def update_region(event: Any, target: tk.Canvas = canvas) -> None:
                target.configure(scrollregion=target.bbox("all"))

            def update_width(event: Any, target: tk.Canvas = canvas, item_id: int = item) -> None:
                target.itemconfigure(item_id, width=event.width)

            page.bind("<Configure>", update_region)
            canvas.bind("<Configure>", update_width)
            self.pages.append(page)
            self.page_canvases.append(canvas)
            self.tabs.add(shell, text=title_text)
        self.labels: dict[str, tk.StringVar] = {}
        self._overview()
        self._carrier()
        self._device()
        self._apps()
        self._logs()
        self._settings()
        ttk.Label(
            outer, text="本机处理 · 不含 iMessage · 不抓包 · 不上传短信", style="Muted.TLabel"
        ).pack(anchor="w", pady=(12, 0))
        root.after(400, self._tick)

    def _palette(self) -> dict[str, str]:
        dark = self.runtime.preferences.theme == "dark"
        if self.runtime.preferences.theme == "system" and sys.platform == "win32":
            import importlib

            winreg = importlib.import_module("winreg")

            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                ) as key:
                    dark = winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
            except OSError:
                pass
        return {
            "bg": "#202020" if dark else "#f5f7fa",
            "fg": "#f3f5f8" if dark else "#172033",
            "card": "#2c2c2c" if dark else "#ffffff",
            "muted": "#b4bdca" if dark else "#58677c",
            "track": "#434b56" if dark else "#e2e8f1",
            "blue": "#60b5ff" if dark else "#0078d4",
            "orange": "#ffc06e" if dark else "#995500",
            "red": "#ff8b8b" if dark else "#bd252b",
            "secondary": "#b4bdca" if dark else "#58677c",
        }

    def _styles(self) -> None:
        p = self.palette
        for canvas in getattr(self, "page_canvases", []):
            canvas.configure(background=p["bg"])
        # Ttk uses system controls on light Windows; dark uses its bundled theme,
        # not an external theme package or a WebView skin.
        theme = "vista" if p["bg"] != "#202020" and "vista" in self.style.theme_names() else "clam"
        self.style.theme_use(theme)
        self.root.configure(background=p["bg"])
        self.style.configure(
            ".", font=("Microsoft YaHei UI", 10), background=p["bg"], foreground=p["fg"]
        )
        self.style.configure("TFrame", background=p["bg"])
        self.style.configure("TLabel", background=p["bg"], foreground=p["fg"])
        self.style.configure("Title.TLabel", font=("Segoe UI", 24, "bold"))
        self.style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        self.style.configure("Muted.TLabel", foreground=p["muted"])
        self.style.configure("Status.TLabel", foreground=p["blue"])
        self.style.configure("Metric.TLabel", font=("Segoe UI", 23, "bold"))
        self.style.configure("TButton", padding=(12, 7))
        self.style.configure("TNotebook.Tab", padding=(14, 9))
        self.style.configure(
            "Treeview", rowheight=34, fieldbackground=p["card"], background=p["card"]
        )

    def label(self, parent: Any, key: str, *, style: str = "TLabel") -> None:
        variable = self.labels[key] = tk.StringVar(value="—")
        ttk.Label(parent, textvariable=variable, wraplength=800, style=style).pack(
            anchor="w", pady=6
        )

    @staticmethod
    def heading(parent: Any, title: str, detail: str) -> None:
        ttk.Label(parent, text=title, style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(parent, text=detail, style="Muted.TLabel", wraplength=790).pack(
            anchor="w", pady=(0, 18)
        )

    def _overview(self) -> None:
        page = self.pages[0]
        self.heading(
            page, "连接，始终有备选", "Wi-Fi 优先 · 获得授权并且套餐额度可用时，4G 接管中断的连接。"
        )
        self.label(page, "connection", style="Heading.TLabel")
        self.label(page, "speed", style="Metric.TLabel")
        self.label(page, "totals")
        self.label(page, "percent", style="Usage.TLabel")
        self.label(page, "policy", style="Status.TLabel")
        self.label(page, "diagnostic", style="Muted.TLabel")
        row = ttk.Frame(page)
        row.pack(anchor="w", pady=20)
        ttk.Button(row, text="开启 4G…", command=self.enable).pack(side="left", padx=(0, 10))
        ttk.Button(row, text="关闭 4G", command=lambda: self.runtime.command("off")).pack(
            side="left"
        )
        self.auto = tk.BooleanVar(value=self.runtime.preferences.auto_takeover)
        ttk.Checkbutton(
            page,
            text="Wi-Fi 中断时自动接管（需要管理员权限）",
            variable=self.auto,
            command=self.toggle_auto,
        ).pack(anchor="w", pady=8)
        ttk.Label(
            page,
            text="低于 80%：允许使用    达到 80%：确认后继续    达到 98%：自动停止\n"
            "套餐回复超过 6 小时或计量失效时暂停。运营商计费延迟可能导致估算差异。",
            style="Muted.TLabel",
            wraplength=780,
        ).pack(anchor="w", pady=10)

    def _carrier(self) -> None:
        page = self.pages[1]
        self.heading(page, "每一份流量，都看得见", "运营商套餐快照 + 本机后续计量；不是实时账单。")
        row = ttk.Frame(page)
        row.pack(fill="x")
        self.ring = tk.Canvas(
            row, width=190, height=190, highlightthickness=0, background=self.palette["bg"]
        )
        self.ring.pack(side="left", padx=(0, 25))
        info = ttk.Frame(row)
        info.pack(side="left", fill="x", expand=True)
        self.label(info, "usage", style="Heading.TLabel")
        self.label(info, "stamp", style="Muted.TLabel")
        self.label(info, "usage_band", style="UsageBand.TLabel")
        stages = ttk.Frame(page)
        stages.pack(fill="x", pady=(12, 4))
        self.stage_cards = []
        for index in range(3):
            card = tk.Label(
                stages,
                padx=14,
                pady=10,
                justify="left",
                highlightthickness=1,
                font=("Microsoft YaHei UI", 10),
            )
            card.grid(row=0, column=index, sticky="nsew", padx=(0, 8))
            stages.columnconfigure(index, weight=1)
            self.stage_cards.append(card)
        self.label(page, "carrier_policy", style="Muted.TLabel")
        self.label(page, "session")
        form = ttk.Frame(page)
        form.pack(anchor="w", pady=15)
        ttk.Label(form, text="服务号").grid(row=0, column=0, sticky="w")
        self.number = tk.StringVar(value="10001")
        ttk.Combobox(
            form,
            textvariable=self.number,
            values=("10001", "10086", "10010"),
            state="readonly",
            width=12,
        ).grid(row=1, column=0, padx=(0, 15))
        ttk.Label(form, text="查询指令（请核实当地运营商）").grid(row=0, column=1, sticky="w")
        self.code = tk.StringVar(value="108")
        ttk.Entry(form, textvariable=self.code, width=22).grid(row=1, column=1)
        ttk.Button(form, text="查询一次…", command=self.query).grid(row=1, column=2, padx=15)
        ttk.Label(
            page,
            text="查询会发送一条 SMS，可能收费；不定时发送、不自动重试。\n"
            "只提取套餐数值，不保存短信正文，不删除模块短信。存储已满时请自行管理。",
            style="Muted.TLabel",
            wraplength=780,
        ).pack(anchor="w", pady=12)

    def _device(self) -> None:
        page = self.pages[2]
        self.heading(
            page, "设备与网络", "只控制 VID/PID 匹配的唯一模块网卡；不安装驱动，不刷固件。"
        )
        self.label(page, "device", style="Heading.TLabel")
        self.label(page, "modem")
        self.label(page, "network")
        ttk.Button(page, text="重新检测模块", command=lambda: self.runtime.command("rescan")).pack(
            anchor="w", pady=18
        )
        ttk.Label(
            page,
            text="无 AT 串口：检查官方驱动、设备管理器及其他控制软件占用。\n"
            "无网络接口：当前 USB personality 可能不受 Windows 系统驱动支持。\n"
            "不会自动改成 MBIM／RNDIS、替换驱动、关闭签名验证或修改 VPN／DNS。",
            style="Muted.TLabel",
            wraplength=780,
        ).pack(anchor="w", pady=10)

    def _apps(self) -> None:
        page = self.pages[3]
        self.heading(page, "应用网络", "TCP 字节汇总 · 不抓包、不显示连接地址 · 不等于 SIM 账单")
        self.app_note = tk.StringVar(value="仅在此页面可见时采样；需要管理员权限。")
        ttk.Label(page, textvariable=self.app_note, style="Muted.TLabel", wraplength=790).pack(
            anchor="w", pady=8
        )
        self.app_table = ttk.Treeview(
            page, columns=("name", "down", "up", "total"), show="headings", height=8
        )
        for key, title, width in (
            ("name", "应用 / 进程", 260),
            ("down", "下载", 150),
            ("up", "上传", 150),
            ("total", "观测累计", 150),
        ):
            self.app_table.heading(key, text=title)
            self.app_table.column(key, width=width, anchor="w")
        self.app_table.pack(fill="both", expand=True)
        self._app_busy = False
        self._app_monitor: Any = None

    def _logs(self) -> None:
        page = self.pages[4]
        self.heading(
            page, "运行日志", "仅保留内存中最近 500 条中文事件，不记录正文、账号或原始异常。"
        )
        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 10))
        self.warnings = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="仅警告", variable=self.warnings).pack(side="left")
        ttk.Button(row, text="复制", command=self.copy_logs).pack(side="right")
        ttk.Button(row, text="清空", command=self.runtime.log.clear).pack(side="right", padx=8)
        self.log_text = tk.Text(
            page,
            wrap="word",
            state="disabled",
            borderwidth=0,
            background=self.palette["card"],
            foreground=self.palette["fg"],
            font=("Microsoft YaHei UI", 10),
            padx=12,
            pady=12,
        )
        scroll = ttk.Scrollbar(page, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self._log_cache = ""

    def _settings(self) -> None:
        page = self.pages[5]
        self.heading(
            page, "按你的方式工作", "首版使用系统主题控件与原生托盘；不含任何 iMessage 功能。"
        )
        self.login = tk.BooleanVar(value=login_enabled() if sys.platform == "win32" else False)
        ttk.Checkbutton(
            page, text="登录 Windows 时启动", variable=self.login, command=self.toggle_login
        ).pack(anchor="w", pady=10)
        ttk.Label(
            page,
            text="登录启动不会绕过 UAC；未取得网络控制权限时仅检测，不自动接管。",
            style="Muted.TLabel",
            wraplength=780,
        ).pack(anchor="w", pady=8)
        row = ttk.Frame(page)
        row.pack(anchor="w", pady=15)
        ttk.Label(row, text="外观（重启生效）").pack(side="left", padx=(0, 15))
        self.theme = tk.StringVar(
            value={"system": "跟随系统", "light": "浅色", "dark": "深色"}[
                self.runtime.preferences.theme
            ]
        )
        choice = ttk.Combobox(
            row,
            textvariable=self.theme,
            state="readonly",
            values=("跟随系统", "浅色", "深色"),
            width=14,
        )
        choice.pack(side="left")
        choice.bind("<<ComboboxSelected>>", self.save_theme)
        ttk.Button(page, text="以管理员权限重新启动…", command=self.elevate).pack(
            anchor="w", pady=12
        )
        ttk.Label(
            page,
            text="仅网络开关／保护和应用 TCP 统计需要管理员权限。\n"
            "请只运行可信安装包；本预览版尚未代码签名，Windows 可能显示安全提示。\n"
            "关闭窗口将保留托盘运行；点击“退出”会先尝试关闭 4G 数据。",
            style="Muted.TLabel",
            wraplength=780,
        ).pack(anchor="w", pady=10)
        ttk.Label(
            page,
            text=f"4G Bridge  {VERSION}  ·  Windows x64\n"
            "Python / Tcl-Tk · 原生 Win32 适配 · 开源依赖许可证随安装包提供",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=18)

    def enable(self) -> None:
        state = self.runtime.budget.status().state
        if state == "confirmation":
            self.consent80()
        elif state != "ready":
            messagebox.showwarning("流量保护", STATE_NAMES[state], parent=self.root)
        elif messagebox.askokcancel(
            "开启 4G",
            "将启用模块网卡，可能使用 SIM 流量。Wi-Fi 恢复后自动关闭。\n确认继续？",
            parent=self.root,
        ):
            self.runtime.command("on")

    def consent80(self) -> None:
        if self.runtime.budget.status().state != "confirmation":
            return
        self.show()
        if messagebox.askokcancel(
            "套餐已使用至少 80%",
            "继续使用可能接近套餐上限。\n本次同意仅对当前连接有效，达到 98% 仍会关闭并锁定。",
            parent=self.root,
        ):
            self.runtime.budget.approved = True
            self.runtime.command("on")

    def toggle_auto(self) -> None:
        enabled = self.auto.get()
        if enabled and not messagebox.askokcancel(
            "允许自动接管",
            "Wi-Fi 中断或联网检测连续失败时允许启用 4G，"
            "会消耗 SIM 流量。有效套餐快照与 80% / 98% 保护始终生效。",
            parent=self.root,
        ):
            self.auto.set(False)
            return
        try:
            self.runtime.authorize_auto(enabled)
        except Exception as error:
            self.auto.set(self.runtime.preferences.auto_takeover)
            messagebox.showwarning("未启用", str(error), parent=self.root)

    def query(self) -> None:
        number, code = self.number.get(), self.code.get()
        from fourg_bridge.cellular.carrier_query import query_pdu

        try:
            query_pdu(number, code)
            if messagebox.askokcancel(
                "发送运营商查询",
                f"向 {number} 发送 {code}？\n可能产生短信费用。"
                "只发送一次，不开启数据、不删除回复。",
                parent=self.root,
            ):
                self.runtime.query(number, code)
        except Exception as error:
            messagebox.showwarning("查询未发送", str(error), parent=self.root)

    def toggle_login(self) -> None:
        try:
            set_login(self.login.get())
            self.runtime.log.add("login")
        except Exception:
            messagebox.showwarning(
                "登录启动", "操作未成功。请先安装应用，并检查当前用户权限。", parent=self.root
            )
        self.login.set(login_enabled())

    def save_theme(self, event: Any = None) -> None:
        self.runtime.preferences.theme = {"跟随系统": "system", "浅色": "light", "深色": "dark"}[
            self.theme.get()
        ]
        self.runtime.preferences.save(self.runtime.directory / "settings.json")

    def elevate(self) -> None:
        if self.smoke or sys.platform != "win32":
            return
        if native.is_admin():
            messagebox.showinfo("网络权限", "当前已具有管理员权限。", parent=self.root)
            return
        if not getattr(sys, "frozen", False):
            messagebox.showinfo(
                "开发模式", "请在管理员终端启动，或使用打包后的应用。", parent=self.root
            )
            return
        if not messagebox.askokcancel(
            "管理员权限",
            "将请求 Windows UAC 授权后重新启动。不会安装驱动、更改安全策略或自动发送短信。",
            parent=self.root,
        ):
            return
        shell = native.dll("shell32")
        shell.ShellExecuteW.argtypes = [
            c.c_void_p,
            c.c_wchar_p,
            c.c_wchar_p,
            c.c_wchar_p,
            c.c_wchar_p,
            c.c_int,
        ]
        shell.ShellExecuteW.restype = c.c_void_p
        # New process waits for this instance to exit before acquiring the mutex.
        result = shell.ShellExecuteW(
            None, "runas", sys.executable, subprocess.list2cmdline(["--wait-instance"]), None, 1
        )
        if result and result > 32:
            self.runtime._stop.set()
            self.destroy()
        else:
            messagebox.showwarning("权限未授予", "保持当前只读模式。", parent=self.root)

    def copy_logs(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.runtime.log.text(self.warnings.get()))

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def hide(self) -> None:
        if self.tray and self.tray.available:
            self.root.withdraw()
        else:
            self.root.iconify()

    def quit(self) -> None:
        if self.smoke:
            self.destroy()
            return
        if self._busy:
            return
        self._busy = True
        self.status.set("正在关闭 4G 并退出…")
        threading.Thread(
            target=lambda: self._ui_queue.put(("quit", self.runtime.shutdown())), daemon=True
        ).start()

    def destroy(self) -> None:
        if self.tray:
            self.tray.close()
        self.root.destroy()

    def render_usage(self, fraction: float | None) -> None:
        """Render a supplied estimate only; never mutate budget or grant consent."""
        visual = usage_style(fraction)
        canvas, p = self.ring, self.palette
        color = p[visual.color]
        self.style.configure("Usage.TLabel", foreground=color, font=("Segoe UI", 28, "bold"))
        self.style.configure("UsageBand.TLabel", foreground=color)
        self.labels["percent"].set(f"{visual.percent}  套餐估算已用")
        self.labels["usage_band"].set(visual.title)
        for index, (card, title, detail) in enumerate(
            zip(
                self.stage_cards,
                ("低于 80%", "80% 至 98%", "达到 98%"),
                ("按保护状态使用", "确认后继续", "自动停止"),
                strict=True,
            )
        ):
            selected = visual.stage == index
            card.configure(
                text=f"{'● 当前区间 · ' if selected else ''}{title}\n{detail}",
                background=p["card"],
                foreground=color if selected else p["muted"],
                highlightbackground=color if selected else p["track"],
                highlightcolor=color if selected else p["track"],
            )
        canvas.configure(background=p["bg"])
        canvas.delete("all")
        canvas.create_oval(18, 18, 172, 172, outline=p["track"], width=12)
        arc_fraction = min(1, max(0, fraction)) if visual.stage is not None and fraction else 0
        if arc_fraction:
            canvas.create_arc(
                18,
                18,
                172,
                172,
                start=90,
                extent=-arc_fraction * 359.99,
                style="arc",
                outline=color,
                width=12,
                tags="usage-arc",
            )
        canvas.create_text(
            95,
            86,
            text=visual.percent,
            fill=color,
            font=("Segoe UI", 30, "bold"),
            tags="usage-value",
        )
        canvas.create_text(
            95, 117, text="套餐估算已用", fill=p["muted"], font=("Microsoft YaHei UI", 10)
        )

    def _tick(self) -> None:
        try:
            while not self._ui_queue.empty():
                kind, value = self._ui_queue.get_nowait()
                if kind == "quit":
                    if value:
                        self.destroy()
                        return
                    self._busy = False
                    messagebox.showwarning(
                        "尚未安全退出",
                        "未确认 4G 关闭。请先取得管理员权限或手动禁用模块网卡。",
                        parent=self.root,
                    )
                elif kind == "apps":
                    self._app_busy = False
                    rows, note = value
                    self.app_note.set(note)
                    self.app_table.delete(*self.app_table.get_children())
                    for row in rows:
                        self.app_table.insert(
                            "",
                            "end",
                            values=(
                                row.name,
                                amount(row.download) + "/s",
                                amount(row.upload) + "/s",
                                amount(row.total),
                            ),
                        )
            while not self.runtime.events.empty():
                event = self.runtime.events.get_nowait()
                if event.kind == "consent80":
                    self.consent80()
                elif event.kind in {"query_result", "error"}:
                    self.show()
                    messagebox.showinfo("4G Bridge", event.message, parent=self.root)
            runtime = self.runtime
            self.status.set(runtime.status)
            self.auto.set(runtime.preferences.auto_takeover)
            adapter = runtime.inventory.modem()
            self.labels["connection"].set(
                "数据保护状态未确认"
                if runtime.protection_failed
                else "4G 数据已开启"
                if runtime.data_on
                else "4G 数据关闭"
            )
            self.labels["device"].set(
                "QDC507 · USB 已连接" if runtime.inventory.usb_present else "等待连接 QDC507"
            )
            self.labels["modem"].set(runtime.modem_status)
            self.labels["network"].set(
                f"接口：{adapter.name}  /  #{adapter.index}\nIPv4：{adapter.ipv4 or '未取得'}\n"
                f"网关：{adapter.gateway or '未取得'}\n"
                "默认接口："
                + (", ".join(a.name for a in runtime.inventory.adapters if a.default) or "未取得")
                if adapter
                else "未发现唯一兼容网卡（不按名称猜测设备）"
            )
            t = runtime.traffic
            self.labels["speed"].set(f"↓ {amount(t.download_bps)}/s     ↑ {amount(t.upload_bps)}/s")
            totals = runtime.ledger.usage()
            self.labels["totals"].set(
                f"今日 {amount(totals.today_rx + totals.today_tx)}    ·    "
                f"本月 {amount(totals.month_rx + totals.month_tx)}"
            )
            self.labels["session"].set(
                f"本次观测 ↓ {amount(t.session_rx_bytes)}    ↑ {amount(t.session_tx_bytes)}"
            )
            usage = runtime.budget.usage()
            state = runtime.budget.status().state
            self.labels["policy"].set(STATE_NAMES[state])
            self.labels["diagnostic"].set(
                runtime.diagnostic.title + "\n" + runtime.diagnostic.action
            )
            self.labels["carrier_policy"].set(f"数据保护：{STATE_NAMES[state]}")
            self.labels["usage"].set(
                f"已用 {amount(usage.used_bytes)}\n总量 {amount(usage.total_bytes)}"
                if usage
                else "等待完整套餐回复"
            )
            self.labels["stamp"].set(
                f"短信快照 {usage.timestamp:%m-%d %H:%M}\n套餐＋本机新增 · 估算"
                if usage
                else "请确认后查询一次运营商"
            )
            self.render_usage(usage.fraction if usage else None)
            logs = runtime.log.text(self.warnings.get())
            if logs != self._log_cache:
                self._log_cache = logs
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.insert("end", logs)
                self.log_text.configure(state="disabled")
                self.log_text.see("end")
            if self.tray:
                self.tray.tooltip(
                    "4G Bridge · "
                    + ("4G 已开启" if runtime.data_on else "4G 已关闭")
                    + " · "
                    + STATE_NAMES[state]
                )
            if not self.smoke and self.tabs.index(self.tabs.select()) == 3 and not self._app_busy:
                self._app_busy = True
                threading.Thread(target=self._sample_apps, daemon=True).start()
        except Exception:
            # UI stays alive even if a local store or device vanishes.
            self.status.set("状态刷新暂不可用；请查看设备及流量保护状态")
        self.root.after(1000, self._tick)

    def _sample_apps(self) -> None:
        try:
            from fourg_bridge.windows.app_traffic import AppMonitor

            if self._app_monitor is None:
                self._app_monitor = AppMonitor()
            result = self._app_monitor.sample()
        except Exception:
            result = ([], "统计不可用。需要管理员权限及系统 TCP 统计支持；不使用演示数据。")
        self._ui_queue.put(("apps", result))
