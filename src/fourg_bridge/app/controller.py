from __future__ import annotations

import threading
from dataclasses import replace
from importlib import resources
from pathlib import Path

import AppKit
import Foundation
from PyObjCTools import AppHelper

from fourg_bridge.app.runtime import ModemRuntime
from fourg_bridge.imessage.bridge import MessagesBridge
from fourg_bridge.imessage.runner import AppleScriptRunner
from fourg_bridge.models import DataState, DeviceState, ModemSnapshot, RelayError, RelayStatus
from fourg_bridge.modem.usb_discovery import USBDiscovery
from fourg_bridge.storage.database import RelayDatabase
from fourg_bridge.storage.keychain import KeychainError, KeychainStore
from fourg_bridge.storage.settings import Settings, SettingsStore
from fourg_bridge.support.privacy import redact_identifier
from fourg_bridge.ui.menu_bar import MenuBarController
from fourg_bridge.ui.settings_window import SettingsWindowController


class ApplicationController:
    def __init__(self) -> None:
        support = Path.home() / "Library" / "Application Support" / "4G Bridge"
        self._settings_store = SettingsStore(support / "settings.json")
        self._settings = self._settings_store.load()
        self._keychain = KeychainStore()
        self._database = RelayDatabase(support / "relay.sqlite")
        script = resources.files("fourg_bridge.imessage.resources").joinpath("relay.applescript")
        self._bridge = MessagesBridge(AppleScriptRunner(Path(str(script))), self._keychain)
        self._discovery = USBDiscovery()
        self._snapshot = ModemSnapshot()
        self._runtime: ModemRuntime | None = None
        self._runtime_lock = threading.RLock()
        self._menu = MenuBarController.alloc().initWithDelegate_(self)
        self._settings_window = SettingsWindowController.alloc().initWithDelegate_(self)
        self._rescan_lock = threading.Lock()
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
        self._force_data_off("sleep")

    def workspaceDidWake_(self, _notification) -> None:
        self._force_data_off("wake")
        self.rescan()

    def rescan(self) -> None:
        if not self._rescan_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._rescan_worker, name="QDC507-Discovery", daemon=True).start()

    def _rescan_worker(self) -> None:
        try:
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
                        self._menu.setTrafficSnapshot_usage_,
                        self._runtime.traffic_snapshot,
                        self._runtime.traffic_usage,
                    )
                    if self._settings.relay_enabled:
                        recent = self._runtime.poll_sms()
                        if recent:
                            AppHelper.callAfter(self._menu.setRelayStatus_recent_, True, recent)
            AppHelper.callAfter(self._apply_snapshot, snapshot)
        except Exception as error:
            snapshot = ModemSnapshot(
                device_state=DeviceState.ERROR,
                data_state=DataState.OFF,
                warning=type(error).__name__,
            )
            AppHelper.callAfter(self._apply_snapshot, snapshot)
        finally:
            self._rescan_lock.release()

    def _apply_snapshot(self, snapshot: ModemSnapshot) -> None:
        previously_connected = self._snapshot.descriptor is not None
        self._snapshot = snapshot
        if previously_connected and snapshot.descriptor is None:
            self._force_data_off("USB disconnect")
        self._menu.update_(snapshot)

    def toggle_data(self) -> None:
        if self._snapshot.data_state == DataState.ON:
            self._force_data_off("user")
            return
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("开启 QDC507 4G 数据？")
        alert.setInformativeText_(
            "此操作可能产生 SIM 流量费用。4G Bridge 不会修改 DNS、VPN 或静态路由。"
        )
        alert.addButtonWithTitle_("开启")
        alert.addButtonWithTitle_("取消")
        if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
            return
        with self._runtime_lock:
            transition = self._runtime.set_data(True, True) if self._runtime else None
        if transition is None or transition.current != DataState.ON:
            self._show_alert("尚未发现可安全控制的 QDC507 网络服务", "请确认模块已连接并重新检测。")
            return
        self._snapshot = replace(self._snapshot, data_state=transition.current)
        self._menu.update_(self._snapshot)

    def _force_data_off(self, _reason: str) -> None:
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

    def relay_enabled(self) -> bool:
        return self._settings.relay_enabled

    def set_relay_enabled(self, enabled: bool) -> None:
        self._settings = Settings(enabled, self._settings.poll_interval_seconds)
        self._settings_store.save(self._settings)
        self._menu.setRelayStatus_recent_(enabled, None)

    def relay_target(self) -> str | None:
        try:
            return self._keychain.get_target()
        except KeychainError:
            return None

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
                f"USB 配置：{snapshot.usb_configuration or '—'}",
                f"SIM：{snapshot.sim_state.value.upper()}",
                f"ICCID：{redact_identifier(snapshot.iccid)}",
                f"号码：{redact_identifier(snapshot.phone_number)}",
                f"运营商 / RAT：{snapshot.operator or '—'} / {snapshot.rat or '—'}",
                f"接口 / 服务：{snapshot.interface or '—'} / {snapshot.network_service or '—'}",
                f"IPv4 / 网关：{snapshot.ipv4 or '—'} / {snapshot.gateway or '—'}",
                f"默认接口 / VPN：{snapshot.default_interface or '—'} / {vpn}",
                "Wi‑Fi 与 4G 同时连接时默认流量优先走 Wi‑Fi。",
                "4G 数据在启动、重连、睡眠、唤醒及退出时保持关闭。",
            )
        )

    def set_relay_target(self, target: str) -> None:
        try:
            self._keychain.set_target(target)
            self._show_alert("已保存", "转发目标已安全存入 macOS 钥匙串。")
        except KeychainError:
            self._show_alert("保存失败", "无法写入 macOS 钥匙串。")

    def relay_queue_summary(self) -> str:
        unknown = self._database.records_with_status(RelayStatus.DELIVERY_UNKNOWN)
        retry = self._database.records_with_status(RelayStatus.RETRY)
        cleanup = self._database.records_with_status(RelayStatus.CLEANUP_PENDING)
        if not (unknown or retry or cleanup):
            return "转发队列：正常"
        lines = [f"等待重试：{len(retry)}  投递不确定：{len(unknown)}  等待清理：{len(cleanup)}"]
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

    def send_test_message(self) -> None:
        result = self._bridge.send_test()
        if result.accepted:
            self._show_alert("Messages 已接受发送请求", "这不表示对端已经送达。")
            return
        messages = {
            RelayError.AUTOMATION_DENIED: "Automation 权限未授权。请在系统设置中允许控制“信息”。",
            RelayError.IMESSAGE_NOT_CONNECTED: "Messages 未登录或 iMessage 服务未连接。",
            RelayError.TARGET_UNAVAILABLE: "找不到该 iMessage 目标，请检查手机号或 Apple ID。",
            RelayError.MESSAGES_UNAVAILABLE: "Messages.app 不可用。",
            RelayError.SCRIPT_TIMEOUT: "Messages 响应超时。",
        }
        self._show_alert("发送失败", messages.get(result.error, "AppleScript 执行失败。"))

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
        self._force_data_off("terminate")
        with self._runtime_lock:
            if self._runtime:
                self._runtime.close()
                self._runtime = None
        self._timer.invalidate()
