"""Exercise the shipped AppKit UI without USB, Keychain, SMS, or network effects."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import AppKit
import Foundation

from fourg_bridge.cellular.carrier_query import CarrierUsage
from fourg_bridge.models import (
    DataState,
    DeviceDescriptor,
    DeviceState,
    ModemSnapshot,
    RegistrationState,
    SIMState,
    TrafficSnapshot,
)
from fourg_bridge.network.app_traffic import AppTraffic
from fourg_bridge.network.traffic import TrafficUsage
from fourg_bridge.storage.settings import Settings
from fourg_bridge.ui.badge_preview import render_badge_preview
from fourg_bridge.ui.menu_bar import MenuBarController
from fourg_bridge.ui.navigation import DESTINATIONS
from fourg_bridge.ui.settings_window import SettingsWindowController


class PreviewDelegate:
    def __init__(self):
        self.snapshot = ModemSnapshot(
            device_state=DeviceState.CONNECTED,
            descriptor=DeviceDescriptor(0x2C7C, 0x0125),
            sim_state=SIMState.READY,
            operator="CHN-CT",
            rssi_dbm=-73,
            rat="FDD LTE",
            registration=RegistrationState.REGISTERED_HOME,
            interface="en11",
            network_service="EG25G-QDC507 2",
            default_interface="utun4",
            vpn_active=True,
        )
        self.sample = None
        self.usage = TrafficUsage()
        self._appearance = "system"

    def relay_enabled(self):
        return False

    def app_network_state(self):
        return (
            (AppTraffic(0, "Preview App", 12000, 3000, 150000),),
            "界面测试数据 · 非实机流量",
            False,
        )

    def carrier_state(self):
        return False, "尚未发送查询", None

    def carrier_usage(self):
        return CarrierUsage(60 * 1024**3, 12 * 1024**3, datetime.now().astimezone())

    def carrier_policy_status(self):
        return "界面测试：80% 确认，98% 停止 · 非真实套餐"

    def login_status(self):
        return 0, "已关闭"

    def event_log(self, warnings_only=False):
        return "[信息] [系统] 界面测试事件 · 非实机日志" if not warnings_only else ""

    def clear_event_log(self):
        pass

    def data_policy(self):
        return Settings(carrier_policy_enabled=True), 0, "套餐保护已开启 · 自动接管未开启"

    def relay_target(self):
        return None

    def current_snapshot(self):
        return self.snapshot

    def traffic_state(self):
        return self.sample, self.usage

    def recent_relay(self):
        return None

    def appearance(self):
        return self._appearance

    def set_appearance(self, value):
        self._appearance = value

    def modem_details(self):
        return (
            "模块    Baiwang QDC507\nSIM    已就绪\n运营商    中国电信 · LTE\n"
            "网络接口    自动发现\nIPv4    数据关闭\n优先网络    Wi-Fi"
        )

    def relay_queue_summary(self):
        return "转发队列正常"

    def bridge_status(self):
        return (
            False,
            "手机号缺少国家区号或格式无效。请使用 +国家区号手机号（中国大陆为 +86），"
            "或有效的 iMessage 邮箱；保存后重新检查。",
        )


def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    application = AppKit.NSApplication.sharedApplication()
    application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    render_badge_preview(output / "menu-badge-preview.png")
    render_badge_preview(output / "menu-badge-preview-1x.png", scale=1)
    delegate = PreviewDelegate()
    menu = MenuBarController.alloc().initWithDelegate_(delegate)
    window = SettingsWindowController.alloc().initWithDelegate_(delegate)
    window._sidebar.footnote.setStringValue_("界面验证 · 模拟数据，非实机状态")
    window.refresh()
    window.showWindow_(None)
    menu.update_(delegate.current_snapshot())
    for appearance in ("NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"):
        window.window().setAppearance_(AppKit.NSAppearance.appearanceNamed_(appearance))
        panel = menu._panel.view()
        panel.setAppearance_(AppKit.NSAppearance.appearanceNamed_(appearance))
        menu._popover.showRelativeToRect_ofView_preferredEdge_(
            AppKit.NSMakeRect(0, 0, 1, 1), window.window().contentView(), AppKit.NSMaxXEdge
        )
        Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.15)
        )
        assert menu._popover.isShown()
        panel.layoutSubtreeIfNeeded()
        bitmap = panel.bitmapImageRepForCachingDisplayInRect_(panel.bounds())
        panel.cacheDisplayInRect_toBitmapImageRep_(panel.bounds(), bitmap)
        bitmap.representationUsingType_properties_(
            AppKit.NSBitmapImageFileTypePNG, {}
        ).writeToFile_atomically_(str(output / f"{appearance}-panel.png"), True)
        menu._popover.performClose_(None)
        button = menu._status_item.button()
        button.setAppearance_(AppKit.NSAppearance.appearanceNamed_(appearance))
        for state in DataState:
            menu.update_(replace(delegate.snapshot, data_state=state))
            assert menu._status_item.length() == 50
            assert not button.image().isTemplate()
            assert button.image().cacheMode() == AppKit.NSImageCacheNever
            assert button.title() == ""
            assert button.image().size().width == 42
            assert "4G Bridge" in button.accessibilityLabel()
            assert button.isEnabled()  # Dimmed icon remains clickable.
            bitmap = button.bitmapImageRepForCachingDisplayInRect_(button.bounds())
            button.cacheDisplayInRect_toBitmapImageRep_(button.bounds(), bitmap)
            bitmap.representationUsingType_properties_(
                AppKit.NSBitmapImageFileTypePNG, {}
            ).writeToFile_atomically_(str(output / f"{appearance}-menubar-{state.value}.png"), True)
        menu.update_(delegate.snapshot)
        for index in range(8):
            window._tabs.setSelectedTabViewItemIndex_(index)
            assert DESTINATIONS[window._sidebar.table.selectedRow()][0] == index
            Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
                Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.15)
            )
            content = window.window().contentView()
            content.layoutSubtreeIfNeeded()
            bitmap = content.bitmapImageRepForCachingDisplayInRect_(content.bounds())
            content.cacheDisplayInRect_toBitmapImageRep_(content.bounds(), bitmap)
            data = bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
            data.writeToFile_atomically_(str(output / f"{appearance}-{index}.png"), True)
    # Verify keyboard/table navigation and constrained resizing without invoking live actions.
    for row, (index, _title, _icon) in enumerate(DESTINATIONS):
        window._sidebar.table.selectRowIndexes_byExtendingSelection_(
            Foundation.NSIndexSet.indexSetWithIndex_(row), False
        )
        assert window._tabs.selectedTabViewItemIndex() == index
    for width, height in ((1000, 700), (1280, 820)):
        window.window().setContentSize_(AppKit.NSMakeSize(width, height))
        for index in range(8):
            window._tabs.setSelectedTabViewItemIndex_(index)
            window.window().contentView().layoutSubtreeIfNeeded()
            scroll = window._tabs.tabViewItems()[index].viewController().view()
            assert (
                abs(
                    scroll.documentView().frame().size.width
                    - scroll.contentView().bounds().size.width
                )
                < 1
            )
            assert abs(window._tabs.view().frame().size.width - (width - 200)) < 1
            assert (
                scroll.documentView().frame().size.height
                >= scroll.contentView().bounds().size.height - 1
            )
    window.window().setContentSize_(AppKit.NSMakeSize(1040, 760))
    # State and interaction checks run against an inert delegate: no hardware or messaging.
    window._target.setStringValue_("unsaved target")
    window.refresh(False)
    assert window._target.stringValue() == "unsaved target"
    window.showRelay_(None)
    assert window._tabs.selectedTabViewItemIndex() == 2
    window._appearance.setSelectedSegment_(2)
    window.appearanceChanged_(None)
    assert delegate.appearance() == "dark"
    for state in DataState:
        delegate.snapshot = replace(delegate.snapshot, data_state=state)
        window.refresh(False)
        assert bool(window._data_button.isEnabled()) == (
            state not in (DataState.ENABLING, DataState.DISABLING)
        )
    delegate.snapshot = ModemSnapshot()
    window.refresh(False)
    menu.update_(delegate.snapshot)
    assert not menu._panel._data.isEnabled()
    assert not window._data_button.isEnabled()
    assert window._metrics["download"].stringValue() == "—"
    now = datetime.now().astimezone()
    for index in range(3):
        delegate.sample = TrafficSnapshot(
            "en11", now + timedelta(seconds=index * 5), 0, 0, index * 100, index * 50
        )
        window.refresh(False)
    assert len(window._history.samples) == 3
    assert window._metrics["download"].stringValue() == "200.0 B/s"
    delegate.sample = None
    window.refresh(False)
    assert not window._history.samples
    delegate.diagnostic_mode = True
    window.refresh(False)
    menu.update_(delegate.snapshot)
    assert "测试模式" in window.window().title()
    assert "检测已暂停" in window._device_status.stringValue()
    assert window._details["usb"].stringValue() == "测试模式未检测"
    assert window._rescan.title() == "恢复模块控制…"
    assert menu._panel._data.isEnabled()
    assert menu._values["data"].title() == "恢复模块控制…"
    delegate.diagnostic_mode = False
    window.refresh(False)
    menu.update_(delegate.snapshot)
    assert window.window().title() == "4G Bridge"
    assert window._rescan.title() == "重新检测"
    assert len(window._tabs.tabViewItems()) == 8
    assert window._app_table.table.numberOfRows() == 1
    assert window._login.state() == 0
    assert window._carrier_command.stringValue() == "108"
    assert not window._log_text.isEditable()
    assert menu._panel._ring.value.stringValue() == "20.0%"
    menu._panel._ring.update(None)
    assert menu._panel._ring.value.stringValue() == "—"
    assert window._overview_ring.value.stringValue() == "20.0%"
    assert window._carrier_ring.value.stringValue() == "20.0%"
    assert "60.0 GB" in window._budget_usage.stringValue()
    assert not hasattr(window, "_data_limit")
    print(
        "UI_SMOKE_OK: sidebar, eight pages, light/dark, resizing, states and safe interactions",
        flush=True,
    )
    window.window().orderOut_(None)
