from __future__ import annotations

import threading
from contextlib import suppress
from dataclasses import replace
from importlib import resources
from pathlib import Path

import AppKit
import Foundation
from PyObjCTools import AppHelper

from fourg_bridge.app.auto_data import AutoDataMonitor
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
from fourg_bridge.network.failover import Action
from fourg_bridge.network.traffic import TrafficLedger
from fourg_bridge.storage.budget import BudgetStore
from fourg_bridge.storage.database import RelayDatabase
from fourg_bridge.storage.keychain import KeychainError, KeychainStore
from fourg_bridge.storage.settings import SettingsStore
from fourg_bridge.support.privacy import redact_identifier
from fourg_bridge.ui.menu_bar import MenuBarController
from fourg_bridge.ui.settings_window import SettingsWindowController


class ApplicationController:
    def __init__(self) -> None:
        support = Path.home() / "Library" / "Application Support" / "4G Bridge"
        self._settings_store = SettingsStore(support / "settings.json")
        self._settings = self._settings_store.load()
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
        self._menu.setRelayStatus_recent_(self._settings.relay_enabled, None)
        self.rescan()

    def timerFired_(self, _timer) -> None:
        self.rescan()

    def workspaceDidSleep_(self, _notification) -> None:
        self._auto_data.suspended = True
        self._force_data_off("sleep")

    def workspaceDidWake_(self, _notification) -> None:
        self._force_data_off("wake")
        self._auto_data.reset()
        self._auto_data.suspended = False
        self.rescan()

    def rescan(self) -> None:
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
                    snapshot = self._runtime.snapshot()
                    AppHelper.callAfter(
                        self._apply_traffic,
                        self._runtime.traffic_snapshot,
                        self._runtime.traffic_usage,
                    )
                    if self._settings.relay_enabled:
                        recent = self._runtime.poll_sms()
                        if recent:
                            AppHelper.callAfter(self._apply_recent_relay, recent)
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
        if self._data_busy:
            snapshot = replace(snapshot, data_state=self._snapshot.data_state)
        previously_connected = self._snapshot.descriptor is not None
        self._snapshot = snapshot
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
        self._recent_relay = recent
        self._menu.setRelayStatus_recent_(self._settings.relay_enabled, recent)

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
        if self._data_busy:
            return
        self._auto_data.reset()
        self._start_data_change(False)

    def toggle_data(self) -> None:
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

    def _start_data_change(self, enabled: bool, *, automatic: bool = False) -> None:
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

    def _force_data_off(self, _reason: str) -> None:
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
        return self._settings.relay_enabled

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
        unknown = self._database.records_with_status(RelayStatus.DELIVERY_UNKNOWN)
        retry = self._database.records_with_status(RelayStatus.RETRY)
        cleanup = self._database.records_with_status(RelayStatus.CLEANUP_PENDING)
        failed = self._database.records_with_status(RelayStatus.FAILED)
        if not (unknown or retry or cleanup or failed):
            return "没有待处理失败；历史成功只表示 Messages 接受请求，不代表对方已收到。"
        lines = [
            f"等待重试 {len(retry)} · 投递不确定 {len(unknown)} · "
            f"清理 {len(cleanup)} · 失败 {len(failed)}"
        ]
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
        monitor = self._auto_data
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
        self._start_data_change(False)
