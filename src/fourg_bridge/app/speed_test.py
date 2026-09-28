"""UI consent and guard integration, isolated from SMS and modem transactions."""

import threading
from dataclasses import replace

import AppKit
from PyObjCTools import AppHelper

from fourg_bridge.models import DataState
from fourg_bridge.network.connectivity import WiFiProbe
from fourg_bridge.network.ecm import ECMDetector
from fourg_bridge.network.speed_test import PLANS, SpeedState, SpeedTest, TestMode


class SpeedTestController:
    def __init__(self, app):
        self.app = app
        self.state = SpeedState()
        self.cancelled = threading.Event()
        self.busy = False

    def cancel(self):
        self.cancelled.set()

    def permitted(self, mode, epoch, key, cellular):
        app = self.app
        if app.diagnostic_mode or app._query_suspended or app._data_epoch != epoch:
            return False
        if cellular:
            monitor = app._auto_data
            budget = monitor.carrier_budget
            return bool(
                budget
                and budget.key == key
                and not monitor.error
                and budget.status().state == "ready"
                and app.current_snapshot().data_state == DataState.ON
            )
        return mode != TestMode.CELLULAR

    def start(self, mode, profile):
        if self.busy or self.app.diagnostic_mode:
            return
        app = self.app
        try:
            mode = TestMode(mode)
            if profile not in (0, 1):
                raise ValueError
            plan = PLANS[profile]
            snapshot = app.current_snapshot()
            epoch = app._data_epoch
            interface = None
            if mode == TestMode.WIFI:
                interface = WiFiProbe().interface()
                if not interface or WiFiProbe().disconnected(interface):
                    raise ValueError("Wi-Fi 未连接；不会改用 4G 测速。")
            elif mode == TestMode.CELLULAR:
                interface = snapshot.interface
                if not interface or snapshot.data_state != DataState.ON:
                    raise ValueError("请先按现有套餐规则开启 4G；测速不会替你开启数据。")
            cellular = mode == TestMode.CELLULAR or (
                mode == TestMode.CURRENT and snapshot.data_state == DataState.ON
            )
            budget = app._auto_data.carrier_budget
            key = budget.key if budget else None
            if not self.permitted(mode, epoch, key, cellular):
                raise ValueError("网络或套餐保护不允许测速；先检查 80% 确认／98% 停止状态。")
            if cellular:
                quota = budget.status()
                limit = 98 if budget.approved else 80
                # Conservative headroom, not a guarantee of actual carrier accounting.
                if quota.used + plan.payload * 2 >= quota.total * limit / 100:
                    raise ValueError("套餐距离保护线过近，不启动这次测速。")
            route = {
                TestMode.WIFI: f"Wi-Fi · {interface}",
                TestMode.CURRENT: "当前系统路由 · 含 VPN（若开启）",
                TestMode.CELLULAR: f"4G 专项 · {interface}",
            }[mode]
        except Exception as error:
            detail = (
                str(error) if isinstance(error, ValueError) and str(error) else "网络状态暂不可用。"
            )
            app._show_alert("暂不能测速", detail)
            return
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("开始一次网络测速？")
        alert.setInformativeText_(
            f"{route} · {plan.name}：下载 {plan.download // 1024**2} MiB，"
            f"上传 {plan.upload // 1024**2} MiB 随机数据，另有协议开销。\n"
            "服务方 Cloudflare 会看到公网 IP；不上传文件、短信或 Apple ID。"
            "专项先通过当前系统网络向 Cloudflare 解析测速域名（至多 4 KiB 响应）；"
            "下载和上传固定走所选网卡，不改系统 DNS。"
            "结果仅在本次运行内显示，不提交额外分析数据。\n"
            "当前网络模式可能使用 SIM 流量；VPN 会影响结果。可随时停止，"
            "遇到套餐保护、网络切换或睡眠会中止，不自动重试。"
        )
        alert.addButtonWithTitle_("开始测速")
        alert.addButtonWithTitle_("取消")
        if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
            return
        if not self.permitted(mode, epoch, key, cellular):
            app._show_alert("测速已取消", "确认期间网络或套餐状态发生变化。")
            return
        self.busy = True
        self.cancelled = threading.Event()
        self.state = SpeedState(phase="latency", route=route, note="正在准备测速…")
        app._settings_window.refresh(False)

        def worker():
            def allowed():
                return self.permitted(mode, epoch, key, cellular)

            def publish(state):
                # Check route between phases; interface-bound curl never silently falls back.
                if mode == TestMode.CURRENT and ECMDetector.default_interface() != initial_route:
                    self.cancelled.set()
                AppHelper.callAfter(self.update, state)

            try:
                initial_route = (
                    ECMDetector.default_interface() if mode == TestMode.CURRENT else None
                )
                SpeedTest().run(plan, interface, route, self.cancelled, allowed, publish)
            except Exception:
                AppHelper.callAfter(
                    self.update,
                    replace(self.state, phase="failed", note="测速未完成；未自动重试。"),
                )

        threading.Thread(target=worker, name="Speed-Test", daemon=True).start()

    def update(self, state):
        self.state = state
        if not state.running:
            self.busy = False
        self.app._settings_window.refresh(False)
