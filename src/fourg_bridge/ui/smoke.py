"""Exercise the shipped AppKit UI without USB, Keychain, SMS, or network effects."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import AppKit
import Foundation

from fourg_bridge.models import (
    DataState,
    DeviceDescriptor,
    DeviceState,
    ModemSnapshot,
    RegistrationState,
    SIMState,
    TrafficSnapshot,
)
from fourg_bridge.network.traffic import TrafficUsage
from fourg_bridge.storage.settings import Settings
from fourg_bridge.ui.menu_bar import MenuBarController
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

    def data_policy(self):
        return Settings(), 0, "自动接管未开启；请先设置有限额度。"

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
    delegate = PreviewDelegate()
    menu = MenuBarController.alloc().initWithDelegate_(delegate)
    window = SettingsWindowController.alloc().initWithDelegate_(delegate)
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
        for index in range(5):
            window._tabs.setSelectedTabViewItemIndex_(index)
            Foundation.NSRunLoop.currentRunLoop().runUntilDate_(
                Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.15)
            )
            content = window.window().contentView()
            content.layoutSubtreeIfNeeded()
            bitmap = content.bitmapImageRepForCachingDisplayInRect_(content.bounds())
            content.cacheDisplayInRect_toBitmapImageRep_(content.bounds(), bitmap)
            data = bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
            data.writeToFile_atomically_(str(output / f"{appearance}-{index}.png"), True)
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
    print("UI_SMOKE_OK: menu, five pages, light/dark, states and safe interactions", flush=True)
    window.window().orderOut_(None)
