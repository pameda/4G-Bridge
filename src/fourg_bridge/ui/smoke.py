"""Exercise the shipped AppKit UI without USB, Keychain, SMS, or network effects."""

from __future__ import annotations

from pathlib import Path

import AppKit
import Foundation

from fourg_bridge.models import DeviceDescriptor, DeviceState, ModemSnapshot, SIMState
from fourg_bridge.ui.menu_bar import MenuBarController
from fourg_bridge.ui.settings_window import SettingsWindowController


class PreviewDelegate:
    def relay_enabled(self):
        return False

    def relay_target(self):
        return None

    def current_snapshot(self):
        return ModemSnapshot(
            device_state=DeviceState.CONNECTED,
            descriptor=DeviceDescriptor(0x2C7C, 0x0125),
            sim_state=SIMState.READY,
            operator="CHN-CT",
            rssi_dbm=-73,
        )

    def modem_details(self):
        return (
            "模块    Baiwang QDC507\nSIM    已就绪\n运营商    中国电信 · LTE\n"
            "网络接口    自动发现\nIPv4    数据关闭\n优先网络    Wi-Fi"
        )

    def relay_queue_summary(self):
        return "转发队列正常"


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
        for index in range(4):
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
    print("UI_SMOKE_OK: menu, four settings pages, light and dark appearances", flush=True)
    window.window().orderOut_(None)
