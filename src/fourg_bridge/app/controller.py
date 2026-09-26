from __future__ import annotations

import threading
import time
from contextlib import suppress
from dataclasses import replace
from importlib import resources
from pathlib import Path

import AppKit
import Foundation
from PyObjCTools import AppHelper

from fourg_bridge.app.auto_data import AutoDataMonitor
from fourg_bridge.app.login_item import LoginItem
from fourg_bridge.app.runtime import ModemRuntime
from fourg_bridge.cellular.data_control import NetworkSetupControl
from fourg_bridge.imessage.bridge import MessagesBridge
from fourg_bridge.imessage.runner import AppleScriptRunner
from fourg_bridge.imessage.target import InvalidTarget, normalize_target
from fourg_bridge.models import (
    DataState,
    DeviceState,
    ModemSnapshot,
    RelayError,
    RelayResult,
    RelayStatus,
)
from fourg_bridge.modem.usb_discovery import USBDiscovery
from fourg_bridge.network.app_traffic import AppTrafficTracker, read_counters
from fourg_bridge.network.failover import Action
from fourg_bridge.network.traffic import TrafficLedger
from fourg_bridge.storage.budget import BudgetStore
from fourg_bridge.storage.database import RelayDatabase
from fourg_bridge.storage.keychain import KeychainError, KeychainStore
from fourg_bridge.storage.settings import SettingsStore, mac_carrier_policy
from fourg_bridge.support.event_log import EventLog
from fourg_bridge.support.privacy import redact_identifier
from fourg_bridge.ui.menu_bar import MenuBarController
from fourg_bridge.ui.settings_window import SettingsWindowController


class ApplicationController:
    def __init__(self, *, diagnostic_mode: bool = False) -> None:
        self.diagnostic_mode = diagnostic_mode
        self._events = EventLog()
        self._events.add("start")
        self._reply_logged = False
        self._relay_wait_logged = False
        support = Path.home() / "Library" / "Application Support" / "4G Bridge"
        self._settings_store = SettingsStore(support / "settings.json")
        self._settings = mac_carrier_policy(self._settings_store.load())
        self._apply_appearance()
        self._keychain = KeychainStore()
        self._database = RelayDatabase(support / "relay.sqlite")
        script = resources.files("fourg_bridge.imessage.resources").joinpath("relay.applescript")
        self._bridge = MessagesBridge(AppleScriptRunner(Path(str(script))), self._keychain)
        self._discovery = USBDiscovery()
        self._snapshot = ModemSnapshot()
        self._traffic_snapshot = None
        self._traffic_usage = TrafficLedger(support / "traffic.sqlite").usage()
        self._recent_relay = None
        self._bridge_busy = False
        self._bridge_status = "尚未检查 iMessage；连接检查不会发送消息。"
        self._runtime: ModemRuntime | None = None
        self._login_item = LoginItem()
        self._app_tracker = AppTrafficTracker()
        self._app_rows = ()
        self._app_network_status = "打开应用网络或菜单面板后开始观测；只在内存保留。"
        self._app_network_busy = False
        self._app_network_paused = False
        self._carrier_status = "手动发送查询短信后等待运营商回复；不会自动定时查询。"
        self._carrier_busy = False
        self._carrier_resume = False
        self._runtime_lock = threading.RLock()
        self._menu = MenuBarController.alloc().initWithDelegate_(self)
        self._settings_window = SettingsWindowController.alloc().initWithDelegate_(self)
        self._rescan_lock = threading.Lock()
        self._data_busy = False
        self._data_epoch = 0
        self._budget_stopping = threading.Lock()
        try:
            budget = BudgetStore(support / "budget.sqlite")
        except Exception:
            budget = None  # Missing/corrupt accounting must never authorize spending.
        self._auto_data = AutoDataMonitor(self, budget)
        if not self.diagnostic_mode:
            self._auto_data.start()
        timer_factory = (
            Foundation.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_
        )
        self._timer = timer_factory(5.0, self, "timerFired:", None, True)
        workspace_center = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        workspace_center.addObserver_selector_name_object_(
            self, "workspaceDidSleep:", AppKit.NSWorkspaceWillSleepNotification, None
        )
        workspace_center.addObserver_selector_name_object_(
            self, "workspaceDidWake:", AppKit.NSWorkspaceDidWakeNotification, None
        )
        self._menu.setRelayStatus_recent_(self.relay_enabled(), None)
        self.rescan()

    def timerFired_(self, _timer) -> None:
        self.refresh_app_network()
        self.rescan()

    def app_network_state(self):
        return self._app_rows, self._app_network_status, self._app_network_paused

    def event_log(self, warnings_only=False):
        return self._events.text(warnings_only)

    def clear_event_log(self):
        self._events.clear()

    def _event(self, code):
        if hasattr(self, "_events"):
            self._events.add(code)

    def refresh_app_network(self) -> None:
        visible = self._menu._popover.isShown() or (
            self._settings_window.window().isVisible()
            and self._settings_window._tabs.selectedTabViewItemIndex() == 5
        )
        if not visible or self._app_network_paused or self.diagnostic_mode:
            if not self._app_network_busy:
                self._app_tracker.pause()
                self._app_rows = ()
            return
        if self._app_network_busy:
            return
        self._app_network_busy = True

        def worker():
            try:
                rows = self._app_tracker.sample(read_counters(), time.monotonic())
                status = f"{len(rows)} 个进程 · 每 5 秒更新 · 所有网络汇总（含回环）"
            except Exception:
                self._app_tracker.pause()
                rows, status = (), "系统暂未提供应用计数；不会申请提权或显示演示数据。"
            AppHelper.callAfter(self._apply_app_network, rows, status)

        threading.Thread(target=worker, name="App-Network-Counters", daemon=True).start()

    def _apply_app_network(self, rows, status):
        self._app_network_busy = False
        self._app_rows = () if self._app_network_paused else rows
        self._app_network_status = "观测已暂停" if self._app_network_paused else status
        self._settings_window.refresh_app_network()
        self._menu._panel.refresh(self._snapshot)

    def toggle_app_network(self):
        self._app_network_paused = not self._app_network_paused
        if self._app_network_paused:
            self._app_rows = ()
            self._app_network_status = "观测已暂停；累计仅在本次运行保留。"
        self._settings_window.refresh_app_network()
        self.refresh_app_network()

    def show_app_network(self):
        self._settings_window._tabs.setSelectedTabViewItemIndex_(5)
        self.show_settings()
        self.refresh_app_network()

    def login_status(self):
        state = self._login_item.status()
        return state, {
            0: "已关闭",
            1: "已开启",
            2: "等待系统批准：请检查系统设置 → 通用 → 登录项",
            3: "尚未注册；建议先将应用移到“应用程序”",
        }.get(state, "系统登录项服务不可用")

    def set_login_enabled(self, enabled):
        self._event("login")
        ok, state = self._login_item.set_enabled(enabled)
        if not ok:
            self._show_alert(
                "未能更新登录项",
                "请将应用放入“应用程序”，并检查系统设置中的登录项。未更改 4G 数据开关。",
            )
        elif state == 2:
            self._show_alert("需要系统批准", "请在系统设置 → 通用 → 登录项中允许 4G Bridge。")
        self._settings_window.refresh(False)

    def carrier_state(self):
        allowance = getattr(self._runtime, "carrier_allowance", None)
        status = self._carrier_status
        if getattr(self._runtime, "carrier_reply_received", False):
            status = "已收到运营商回复；无法明确识别的套餐信息请在“信息”查看原文。"
        return self._carrier_busy, status, allowance

    def carrier_usage(self):
        if self._settings.carrier_policy_enabled and getattr(self, "_auto_data", None):
            try:
                return self._auto_data.carrier_budget.usage()
            except Exception:
                return None
        return getattr(self._runtime, "carrier_usage", None)

    def carrier_policy_status(self):
        if not self._settings.carrier_policy_enabled:
            return "未启用套餐比例保护"
        try:
            state = self._auto_data.carrier_budget.status()
            description = {
                "ready": "允许使用",
                "confirmation": "已达 80%，再次开启需确认",
                "locked": "已达 98%，数据已锁定",
                "unknown": "等待完整套餐数据",
                "stale": "套餐查询已超过 6 小时，请重新查询",
            }[state.state]
            percent = f"估算已用 {state.used / state.total:.1%} · " if state.total else ""
            return (
                percent
                + description
                + (" · 自动接管已开启" if self._settings.auto_data_enabled else " · 自动接管已关闭")
            )
        except Exception:
            return "套餐计量不可用，禁止自动开启"

    def toggle_carrier_policy(self):
        if self._settings.carrier_policy_enabled and self._settings.auto_data_enabled:
            self._settings = replace(self._settings, auto_data_enabled=False)
            self._settings_store.save(self._settings)
            self._start_data_change(False)
            return
        usage = self.carrier_usage()
        if not usage or not self._auto_data.carrier_budget:
            self._show_alert("需要套餐数据", "请先查询运营商，并确认总量和已用量已被识别。")
            return
        self._auto_data.carrier_budget.update_plan(
            usage, sim_key=self._auto_data.carrier_budget.key
        )
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("允许按套餐上限自动接管？")
        alert.setInformativeText_(
            "Wi-Fi 断开或无互联网时自动请求 4G 接管；80% 前不限速，80% 起需确认，98% 自动关闭。\n"
            "使用运营商快照＋本机新增流量估算，不是实时账单。查询超过 6 小时会暂停，需手动查询；"
            "不会后台发送收费短信。不会关闭 VPN；VPN 自身仍需支持网络切换。"
        )
        alert.addButtonWithTitle_("允许自动接管")
        alert.addButtonWithTitle_("取消")
        if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
            return
        self._settings = replace(
            self._settings, carrier_policy_enabled=True, auto_data_enabled=True
        )
        self._settings_store.save(self._settings)
        self._auto_data.reset()
        self._settings_window.refresh(False)

    def _carrier_consent(self):
        if not self._auto_data.carrier_budget:
            self._show_alert("套餐计量不可用", "无法开启数据，请检查本机计量数据库。")
            return False
        state = self._auto_data.carrier_budget.status()
        if state.state == "ready":
            return True
        if state.state != "confirmation":
            self._show_alert("暂不能开启 4G", self.carrier_policy_status())
            return False
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("套餐已使用超过 80%")
        alert.setInformativeText_(
            self.carrier_policy_status() + "\n确认后仅允许本次连接，达到 98% 仍会自动关闭。"
        )
        alert.addButtonWithTitle_("确认继续本次连接")
        alert.addButtonWithTitle_("保持关闭")
        if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
            self._auto_data.policy.paused = True
            return False
        self._auto_data.carrier_budget.approved = True
        return True

    def query_carrier(self, number, command):
        from fourg_bridge.cellular.carrier_query import query_pdu

        if self._carrier_busy or self.diagnostic_mode or self._runtime is None:
            self._show_alert("暂时无法查询", "请先连接模块并退出测试模式。")
            return
        try:
            query_pdu(number, command)
        except ValueError as error:
            self._show_alert("查询参数无效", str(error))
            return
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("发送运营商流量查询短信？")
        alert.setInformativeText_(
            f"向 {number} 发送：{command}\n可能产生短信费用，不开启 4G 数据。"
            "指令因地区及套餐而异，请核实；不会自动重试或定时发送。"
        )
        alert.addButtonWithTitle_("发送一次")
        alert.addButtonWithTitle_("取消")
        if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
            return
        self._carrier_busy = True
        self._reply_logged = False
        self._event("query")
        self._carrier_status = "正在发送一次查询，请勿重复操作…"
        self._settings_window.refresh(False)

        def worker():
            try:
                with self._runtime_lock:
                    status = (
                        self._runtime.query_carrier(number, command)
                        if self._runtime
                        else "模块已断开，未发送。"
                    )
            except Exception:
                status = "查询未完成；发送结果不确定，请先等待回复，不要立即重试。"
            AppHelper.callAfter(self._carrier_finished, status)

        threading.Thread(target=worker, name="Carrier-Query", daemon=True).start()

    def _carrier_finished(self, status):
        self._event("query_end")
        self._carrier_busy = False
        self._carrier_status = status
        self._settings_window.refresh(False)
        self.rescan()

    def workspaceDidSleep_(self, _notification) -> None:
        self._event("sleep")
        self._auto_data.suspended = True
        self._force_data_off("sleep")

    def workspaceDidWake_(self, _notification) -> None:
        self._event("wake")
        self._force_data_off("wake")
        self._auto_data.reset()
        self._auto_data.suspended = False
        self.rescan()

    def rescan(self) -> None:
        if self.diagnostic_mode:
            return  # Permission/testing UI must not read, relay or delete module SMS.
        if not self._rescan_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._rescan_worker, name="QDC507-Discovery", daemon=True).start()

    def _rescan_worker(self) -> None:
        try:
            conflicts = [
                app.localizedName()
                for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
                if app.bundleIdentifier() in ("com.pantao.dji4g-menubar",)
            ]
            if conflicts:
                AppHelper.callAfter(
                    self._apply_snapshot,
                    ModemSnapshot(
                        device_state=DeviceState.ERROR,
                        warning="请先退出 DJI 4G 控制器，避免两个应用同时控制模块。",
                    ),
                )
                return
            descriptor = self._discovery.discover()
            with self._runtime_lock:
                if descriptor is None:
                    if self._runtime:
                        self._runtime.close()
                        self._runtime = None
                    snapshot = ModemSnapshot(device_state=DeviceState.MISSING)
                else:
                    if self._runtime is None:
                        self._runtime = ModemRuntime(self._discovery, self._database, self._bridge)
                    # SMS relay has no data-state, default-interface, Wi-Fi,
                    # failover or quota gate. Messages uses the Mac's network.
                    relay_ready = False
                    if self._settings.relay_enabled and not self._database.blocked:
                        prerequisite = self._bridge.target_status()
                        if prerequisite.accepted:
                            relay_ready = True
                        else:
                            AppHelper.callAfter(self._relay_waiting, prerequisite)
                    if (
                        relay_ready
                        or getattr(self._runtime, "carrier_pending", False)
                        or getattr(self._runtime, "carrier_cache_pending", False)
                    ):
                        recent = self._runtime.poll_sms(relay_enabled=relay_ready)
                        if recent:
                            AppHelper.callAfter(self._apply_recent_relay, recent)
                    snapshot = self._runtime.snapshot()
                    AppHelper.callAfter(
                        self._apply_traffic,
                        self._runtime.traffic_snapshot,
                        self._runtime.traffic_usage,
                    )
            AppHelper.callAfter(self._apply_snapshot, snapshot)
        except Exception as error:
            with self._runtime_lock:
                if self._runtime:
                    with suppress(Exception):
                        self._runtime.close()
                    self._runtime = None
            snapshot = ModemSnapshot(
                device_state=DeviceState.ERROR,
                data_state=DataState.PROTECTION_FAILED,
                warning=type(error).__name__,
            )
            AppHelper.callAfter(self._apply_snapshot, snapshot)
        finally:
            self._rescan_lock.release()

    def _apply_snapshot(self, snapshot: ModemSnapshot) -> None:
        changed = False
        usage = getattr(self._runtime, "carrier_usage", None)
        monitor = getattr(self, "_auto_data", None)
        if monitor and monitor.carrier_budget:
            try:
                changed = monitor.carrier_budget.bind(
                    snapshot.iccid
                    if snapshot.descriptor and snapshot.sim_state.value == "READY"
                    else None
                )
                if changed and self._runtime:
                    self._runtime.cancel_pending_enable()
            except Exception:
                monitor.error = True
        if usage and getattr(self, "_auto_data", None) and self._auto_data.carrier_budget:
            try:
                self._auto_data.carrier_budget.update_plan(
                    usage, sim_key=getattr(self._runtime, "carrier_sim_key", None)
                )
            except Exception:
                self._auto_data.error = True
        if self._data_busy:
            snapshot = replace(snapshot, data_state=self._snapshot.data_state)
        previously_connected = self._snapshot.descriptor is not None
        if previously_connected != (snapshot.descriptor is not None):
            self._event("connected" if snapshot.descriptor else "missing")
        if self._snapshot.data_state != snapshot.data_state:
            self._event(
                {DataState.ON: "data_on", DataState.OFF: "data_off"}.get(
                    snapshot.data_state, "data_transition"
                )
            )
        if snapshot.warning and snapshot.warning != self._snapshot.warning:
            self._event("warning")
        if getattr(self._runtime, "carrier_reply_received", False) and not self._reply_logged:
            self._event("reply")
            self._reply_logged = True
        self._snapshot = snapshot
        if changed:
            self._start_data_change(False)
            return
        if snapshot.descriptor is None:
            self._apply_traffic(None, self._traffic_usage)
        if previously_connected and snapshot.descriptor is None:
            self._force_data_off("USB disconnect")
        self._menu.update_(snapshot)
        if self._settings_window.window().isVisible():
            self._settings_window.refresh(False)

    def current_snapshot(self) -> ModemSnapshot:
        return self._snapshot

    def _apply_traffic(self, snapshot, usage) -> None:
        self._traffic_snapshot = snapshot
        self._traffic_usage = usage
        self._menu.setTrafficSnapshot_usage_(snapshot, usage)

    def traffic_state(self):
        return self._traffic_snapshot, self._traffic_usage

    def _apply_recent_relay(self, recent: str) -> None:
        if recent != self._recent_relay:
            self._event("relay")
        self._relay_wait_logged = False
        self._recent_relay = recent
        self._menu.setRelayStatus_recent_(self._settings.relay_enabled, recent)

    def _relay_waiting(self, result: RelayResult) -> None:
        if not getattr(self, "_relay_wait_logged", False):
            self._event("relay_wait")
            self._relay_wait_logged = True
        if not self._bridge_busy:
            self._bridge_status = "自动转发等待配置：" + self._relay_error_message(result)

    def recent_relay(self) -> str | None:
        return self._recent_relay

    def appearance(self) -> str:
        return self._settings.appearance

    def _apply_appearance(self) -> None:
        name = {"light": "NSAppearanceNameAqua", "dark": "NSAppearanceNameDarkAqua"}.get(
            self._settings.appearance
        )
        AppKit.NSApp.setAppearance_(AppKit.NSAppearance.appearanceNamed_(name) if name else None)

    def set_appearance(self, value: str) -> None:
        if value not in ("system", "light", "dark"):
            return
        self._settings = replace(self._settings, appearance=value)
        self._settings_store.save(self._settings)
        self._apply_appearance()

    def redetect(self) -> None:
        if self.diagnostic_mode:
            self.request_resume_modem_control()
            return
        if self._data_busy:
            return
        self._auto_data.reset()
        self._start_data_change(False)

    def toggle_data(self) -> None:
        if self.diagnostic_mode:
            self.request_resume_modem_control()
            return
        if self._data_busy:
            return
        if self._snapshot.data_state == DataState.ON:
            self._settings = replace(self._settings, auto_data_enabled=False)
            self._settings_store.save(self._settings)
            self._start_data_change(False)
            return
        if not self._auto_data.ready():
            self._show_alert("流量保护已锁定", "请在设置中手动追加额度；计量异常时请先修复。")
            return
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("开启 QDC507 4G 数据？")
        alert.setInformativeText_(
            "会使用 SIM 流量。若模块无法取得网络地址，将重启模块一次后重试，"
            "恢复可能需要约两分钟。Wi-Fi 可用时优先使用 Wi-Fi。"
        )
        alert.addButtonWithTitle_("开启")
        alert.addButtonWithTitle_("取消")
        if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
            return
        self._start_data_change(True)

    def request_resume_modem_control(self) -> None:
        if not self.diagnostic_mode:
            return
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("退出短信测试模式，恢复模块控制？")
        alert.setInformativeText_(
            "测试模式没有检测 USB，并不表示模块未插入。恢复后先检测模块并关闭 4G 数据；"
            "已授权的自动接管仍遵循原设置及流量限额。\n\n"
            "短信转发会恢复之前保存的开关；开启时可能处理模块中尚未转发的积存短信。"
        )
        alert.addButtonWithTitle_("恢复模块控制")
        alert.addButtonWithTitle_("取消")
        if alert.runModal() == AppKit.NSAlertFirstButtonReturn:
            self.resume_modem_control()

    def resume_modem_control(self) -> None:
        """Exit isolated diagnostics and restore the user's saved relay preference."""
        if not self.diagnostic_mode:
            return
        settings = self._settings
        try:
            self._settings_store.save(settings)
        except OSError:
            self._show_alert("暂未恢复模块控制", "无法保存安全设置，请检查磁盘后重试。")
            return
        self._settings = settings
        self.diagnostic_mode = False
        self._snapshot = replace(self._snapshot, warning="正在检测 QDC507，请稍候。")
        self._menu.setRelayStatus_recent_(self.relay_enabled(), self._recent_relay)
        self._menu.update_(self._snapshot)
        self._settings_window.refresh(False)
        self._auto_data.start()
        self.rescan()

    def _start_data_change(self, enabled: bool, *, automatic: bool = False) -> None:
        if self.diagnostic_mode:
            return
        if enabled and self._settings.carrier_policy_enabled and not self._carrier_consent():
            return
        if enabled and not self._auto_data.ready():
            return
        self._data_epoch += 1
        epoch = self._data_epoch
        self._data_busy = False
        self._apply_snapshot(
            replace(
                self._snapshot,
                warning=None,
                data_state=DataState.ENABLING if enabled else DataState.DISABLING,
            )
        )
        self._data_busy = True

        def worker() -> None:
            try:
                with self._runtime_lock:
                    if enabled:
                        self._auto_data.sample()  # Baseline before any service enable.
                    if enabled and (epoch != self._data_epoch or not self._auto_data.ready()):
                        transition = None
                    else:
                        transition = (
                            self._runtime.set_data(enabled, enabled, automatic=automatic)
                            if self._runtime
                            else None
                        )
                AppHelper.callAfter(self._data_finished, transition, enabled, epoch, automatic)
            except Exception:
                AppHelper.callAfter(self._data_finished, None, enabled, epoch, automatic)

        threading.Thread(target=worker, name="Data-Transition", daemon=True).start()

    def _data_finished(self, transition, requested_on: bool, epoch: int, automatic=False) -> None:
        if epoch != self._data_epoch:
            self.rescan()
            return
        self._data_busy = False
        state = transition.current if transition else DataState.PROTECTION_FAILED
        detail = transition.detail if transition else "未发现可控制的 QDC507 服务，请重新检测。"
        failed = requested_on and state != DataState.ON
        if automatic:
            self._auto_data.completed(
                requested_on, state == (DataState.ON if requested_on else DataState.OFF)
            )
        self._apply_snapshot(
            replace(self._snapshot, data_state=state, warning=detail if failed else None)
        )
        if failed and not automatic:
            self._show_alert("4G 未能连接", detail)
        self.rescan()

        if not requested_on and state == DataState.OFF and self._settings.carrier_policy_enabled:
            self._auto_data.carrier_budget.approved = False
            if self._carrier_resume:
                self._carrier_resume = False
                self._start_data_change(True, automatic=True)

    def _force_data_off(self, _reason: str) -> None:
        if getattr(self, "_auto_data", None) and self._auto_data.carrier_budget:
            self._auto_data.carrier_budget.approved = False
        self._data_epoch += 1
        if self._runtime:
            self._runtime.cancel_pending_enable()
        with self._runtime_lock:
            transition = self._runtime.force_safe_off() if self._runtime else None
        state = transition.current if transition else DataState.OFF
        self._snapshot = replace(self._snapshot, data_state=state)
        self._menu.update_(self._snapshot)

    def show_settings(self) -> None:
        self._settings_window.refresh()
        self._settings_window.showWindow_(None)
        self._settings_window.window().makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)

    def show_overview(self) -> None:
        self._settings_window._tabs.setSelectedTabViewItemIndex_(0)
        self.show_settings()

    def relay_enabled(self) -> bool:
        return self._settings.relay_enabled and not self.diagnostic_mode

    def set_relay_enabled(self, enabled: bool) -> None:
        self._settings = replace(self._settings, relay_enabled=enabled)
        self._settings_store.save(self._settings)
        self._menu.setRelayStatus_recent_(enabled, self._recent_relay)

    def relay_target(self) -> str | None:
        try:
            return self._keychain.get_target()
        except KeychainError:
            self._bridge_status = "钥匙串目标不可读取。请点击“授权读取目标”，完成系统授权后再检查。"
            return None

    def authorize_relay_target(self) -> None:
        if self._bridge_busy:
            return
        self._bridge_busy = True
        self._bridge_status = "等待系统钥匙串授权；可在系统对话框中取消。不会发送消息。"
        self._settings_window.refresh(False)

        def worker() -> None:
            try:
                target = self._keychain.get_target(allow_interaction=True)
                status = (
                    "已授权读取目标，请检查目标格式。" if target else "未保存目标，请填写并保存。"
                )
            except Exception:
                status = "未能获得钥匙串授权。没有发送消息，请重新授权或保存目标。"
            AppHelper.callAfter(self._target_authorized, status)

        threading.Thread(target=worker, name="Keychain-Authorization", daemon=True).start()

    def _target_authorized(self, status: str) -> None:
        self._bridge_busy = False
        self._bridge_status = status
        self._settings_window.refresh()

    def modem_details(self) -> str:
        snapshot = self._snapshot
        descriptor = snapshot.descriptor
        usb = (
            f"{descriptor.vendor_id:04X}:{descriptor.product_id:04X}" if descriptor else "未检测到"
        )
        product = (
            " / ".join(
                value
                for value in (
                    (descriptor.manufacturer if descriptor else None),
                    (descriptor.product if descriptor else None),
                )
                if value
            )
            or "—"
        )
        vpn = "已连接" if snapshot.vpn_active else "未连接"
        return "\n".join(
            (
                f"USB：{usb}  {product}",
                f"模块：{snapshot.modem_identity or '—'}",
                f"SIM：{snapshot.sim_state.value.upper()}",
                f"运营商 / RAT：{snapshot.operator or '—'} / {snapshot.rat or '—'}",
                f"接口 / 服务：{snapshot.interface or '—'} / {snapshot.network_service or '—'}",
                f"IPv4 / 网关：{snapshot.ipv4 or '—'} / {snapshot.gateway or '—'}",
                f"默认接口 / VPN：{snapshot.default_interface or '—'} / {vpn}",
            )
        )

    def set_relay_target(self, target: str) -> bool:
        try:
            self._keychain.set_target(normalize_target(target) if target.strip() else "")
            self._show_alert("已保存", "转发目标已安全存入 macOS 钥匙串。")
            self._bridge_status = "目标已更新，请先检查连接，再发送测试。"
            return True
        except InvalidTarget as error:
            self._show_alert("目标格式需要调整", str(error))
        except KeychainError:
            self._show_alert("保存失败", "无法写入 macOS 钥匙串。")
        return False

    def relay_queue_summary(self) -> str:
        if self._database.blocked:
            return self._database.blocked
        unknown = self._database.records_with_status(RelayStatus.DELIVERY_UNKNOWN)
        retry = self._database.records_with_status(RelayStatus.RETRY)
        cleanup = self._database.records_with_status(RelayStatus.CLEANUP_PENDING)
        failed = self._database.records_with_status(RelayStatus.FAILED)
        blocked = self._database.records_with_status(RelayStatus.CLEANUP_BLOCKED)
        if not (unknown or retry or cleanup or failed or blocked):
            return "没有待处理失败；历史成功只表示 Messages 接受请求，不代表对方已收到。"
        lines = [
            f"等待重试 {len(retry)} · 投递不确定 {len(unknown)} · "
            f"清理 {len(cleanup)} · 失败 {len(failed)}"
        ]
        if blocked:
            lines.append(
                f"安全暂停清理 {len(blocked)} 项：身份或短信内容无法核验；不会重发或删除。"
            )
        if failed or retry:
            record = (failed or retry)[-1]
            try:
                error = RelayError(record.last_error)
            except ValueError:
                error = RelayError.SCRIPT_FAILED
            lines.append(self._relay_error_message(RelayResult(False, error)))
        if unknown:
            record = unknown[0]
            lines.append(
                f"最近不确定项：{record.timestamp[:16].replace('T', ' ')} / "
                f"{redact_identifier(record.sender)}"
            )
        return "\n".join(lines)

    def retry_delivery_unknown(self) -> None:
        records = self._database.records_with_status(RelayStatus.DELIVERY_UNKNOWN)
        for record in records:
            self._database.transition(
                record.message_hash,
                RelayStatus.RETRY,
                retry_count=record.retry_count,
            )
        if records:
            self.rescan()
        self._show_alert("已更新转发队列", f"{len(records)} 项将在模块短信重新读取后发送。")

    def confirm_delivery_unknown(self) -> None:
        records = self._database.records_with_status(RelayStatus.DELIVERY_UNKNOWN)
        for record in records:
            self._database.transition(record.message_hash, RelayStatus.CLEANUP_PENDING)
        if records:
            self.rescan()
        self._show_alert("已更新清理队列", f"{len(records)} 项不会重发，只会清理模块短信。")

    def bridge_status(self) -> tuple[bool, str]:
        return self._bridge_busy, self._bridge_status

    def check_messages(self) -> None:
        self._start_bridge_action(False)

    def send_test_message(self) -> None:
        self._start_bridge_action(True)

    def _start_bridge_action(self, send: bool) -> None:
        if self._bridge_busy:
            return
        self._bridge_busy = True
        self._bridge_status = "正在发送测试…" if send else "正在检查连接（不会发送消息）…"
        self._settings_window.refresh(False)

        def worker() -> None:
            try:
                result = self._bridge.send_test() if send else self._bridge.check()
            except Exception:
                result = RelayResult(False, RelayError.SCRIPT_FAILED, delivery_uncertain=send)
            AppHelper.callAfter(self._bridge_finished, result, send)

        threading.Thread(
            target=worker, name="Messages-Check" if not send else "Messages-Test", daemon=True
        ).start()

    def _bridge_finished(self, result: RelayResult, send: bool) -> None:
        self._bridge_busy = False
        if result.accepted:
            self._bridge_status = (
                "Messages 已接受测试发送请求；请在“信息”中确认是否出现红色发送失败标记。"
                if send
                else "连接检查通过；未发送消息，也无法仅凭此检查确定对方已开通 iMessage。"
            )
        else:
            self._bridge_status = self._relay_error_message(result)
        self._settings_window.refresh(False)
        self._show_alert("iMessage 测试" if send else "iMessage 连接检查", self._bridge_status)

    @staticmethod
    def _relay_error_message(result: RelayResult) -> str:
        if result.delivery_uncertain:
            return (
                "发送结果不确定。请先在“信息”中核对，不要连续重发；"
                "自动转发将保留模块短信并停止重试。"
            )
        messages = {
            RelayError.AUTOMATION_DENIED: "Automation 权限未授权。请在系统设置中允许控制“信息”。",
            RelayError.IMESSAGE_NOT_CONNECTED: "Messages 未登录或 iMessage 服务未连接。",
            RelayError.TARGET_UNAVAILABLE: "找不到该 iMessage 目标，请检查手机号或 Apple ID。",
            RelayError.MESSAGES_UNAVAILABLE: "Messages.app 不可用。",
            RelayError.SCRIPT_TIMEOUT: "Messages 响应超时。",
            RelayError.TARGET_INVALID: (
                "手机号缺少国家区号或格式无效。请使用 +国家区号手机号"
                "（中国大陆为 +86），或有效的 iMessage 邮箱；保存后重新检查。"
            ),
            RelayError.KEYCHAIN_UNAVAILABLE: (
                "无法读取钥匙串目标。请点击“授权读取目标”，完成系统授权后再检查。"
            ),
        }
        return messages.get(result.error, f"AppleScript 执行失败。{result.detail}")

    @staticmethod
    def _show_alert(title: str, detail: str) -> None:
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(detail)
        alert.runModal()

    def quit(self) -> None:
        self._force_data_off("quit")
        AppKit.NSApp.terminate_(None)

    def close(self) -> None:
        self._auto_data.stop.set()
        self._force_data_off("terminate")
        with self._runtime_lock:
            if self._runtime:
                self._runtime.close()
                self._runtime = None
        self._timer.invalidate()

    def data_policy(self):
        if not hasattr(self, "_auto_data"):
            return self._settings, 0, "正在启动流量保护"
        monitor = self._auto_data
        if self._settings.carrier_policy_enabled:
            return self._settings, 0, self.carrier_policy_status()
        available = monitor.ready()
        status = monitor.status if self._settings.auto_data_enabled else "自动接管未开启"
        if not available:
            status = "流量保护锁定／计量不可用；请手动追加额度或检查计量。"
        budget = monitor.budget_status
        used = budget.used if budget else 0
        return self._settings, used, status

    def save_data_policy(self, enabled: bool, limit_gb: str, monthly: bool) -> bool:
        from decimal import Decimal, InvalidOperation

        try:
            value = Decimal(limit_gb)
            if not value.is_finite() or value <= 0 or value > 10000:
                raise ValueError
            limit = int(value * 1_000_000_000)
            if limit < 1_000_000:
                raise ValueError
        except (InvalidOperation, ValueError):
            self._show_alert("请输入有效上限", "使用 0.001 至 10000 GB；1 GB = 10 亿字节。")
            return False
        if self._auto_data.budget is None:
            self._show_alert("计量数据库不可用", "为防止超额，不能启用；原始计量文件未被覆盖。")
            return False
        self._settings = replace(
            self._settings,
            auto_data_enabled=enabled,
            data_limit_bytes=limit,
            data_budget_period="month" if monthly else "allowance",
        )
        self._settings_store.save(self._settings)
        self._auto_data.reset()
        # Saving new settings never clears an existing cap latch.
        if not enabled or not self._auto_data.ready():
            self._start_data_change(False)
        return True

    def grant_data_allowance(self):
        if self._settings.carrier_policy_enabled:
            self._show_alert(
                "套餐保护已生效", "98% 上限不能用追加固定额度绕过。请在运营商页查看套餐状态。"
            )
            return
        try:
            self._auto_data.budget.grant(self._settings.data_limit_bytes, user_confirmed=True)
        except Exception:
            self._show_alert("无法追加额度", "请先保存有效上限，确认计量数据库可用。")
            return
        self._auto_data.error = False
        self._auto_data.reset()
        self._settings_window.refresh()

    def auto_data_request(self, action, epoch):
        if (
            epoch != self._data_epoch
            or self._data_busy
            or self._auto_data.suspended
            or self._auto_data.stop.is_set()
            or not self._settings.auto_data_enabled
        ):
            return
        if action == Action.ENABLE and not self._auto_data.ready():
            return
        if action == Action.ENABLE:
            self._event("auto")
        self._start_data_change(action == Action.ENABLE, automatic=True)

    def stop_for_budget(self):
        """Guard thread: cut ECM without waiting behind SMS/AT/AppleScript."""
        if not self._budget_stopping.acquire(blocking=False):
            return
        try:
            self._data_epoch += 1
            runtime = self._runtime
            if runtime:
                runtime.cancel_pending_enable()
            snapshot = self._snapshot
            if snapshot.network_service:
                control = NetworkSetupControl(snapshot.interface)
                control.set_enabled(snapshot.network_service, False)
        finally:
            AppHelper.callAfter(self._budget_stopped)
            self._budget_stopping.release()

    def _budget_stopped(self):
        if self._snapshot.data_state == DataState.DISABLING:
            return
        if self._settings.carrier_policy_enabled and self._auto_data.carrier_budget:
            self._carrier_resume = self._auto_data.carrier_budget.status().state == "confirmation"
            self._event("carrier80" if self._carrier_resume else "carrier98")
        self._start_data_change(False)
