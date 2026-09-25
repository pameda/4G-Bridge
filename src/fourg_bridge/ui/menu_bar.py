from __future__ import annotations

import AppKit
import objc

from fourg_bridge.models import DataState, DeviceState, ModemSnapshot


class MenuBarController(AppKit.NSObject):
    def initWithDelegate_(self, delegate: object):
        self = objc.super(MenuBarController, self).init()
        if self is None:
            return None
        self._delegate = delegate
        self._status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        self._menu = AppKit.NSMenu.alloc().initWithTitle_("4G Bridge")
        self._status_item.setMenu_(self._menu)
        self._values: dict[str, AppKit.NSMenuItem] = {}
        self._build_menu()
        self.update_(ModemSnapshot())
        return self

    def _build_menu(self) -> None:
        heading = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "4G Bridge", None, ""
        )
        heading.setEnabled_(False)
        self._menu.addItem_(heading)
        self._add_value("device", "QDC507", "未连接")
        self._add_value("usb", "USB", "—")
        self._add_value("operator", "运营商", "—")
        self._add_value("sim", "SIM", "未知")
        self._add_value("signal", "信号", "—")
        self._add_value("registration", "LTE", "未注册")
        self._add_value("rat", "RAT", "—")
        self._add_value("interface", "接口", "—")
        self._add_value("ip", "IP", "—")
        self._add_value("gateway", "网关", "—")
        self._add_value("default", "默认接口", "—")
        self._add_value("vpn", "VPN", "未连接")
        self._add_value("download", "当前下载", "—")
        self._add_value("upload", "当前上传", "—")
        self._add_value("session", "本次连接", "—")
        self._add_value("traffic", "今日流量", "—")
        self._add_value("month", "本月流量", "—")
        self._menu.addItem_(AppKit.NSMenuItem.separatorItem())

        data = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "开启 4G 数据…", "toggleData:", ""
        )
        data.setTarget_(self)
        self._menu.addItem_(data)
        self._values["data"] = data

        self._add_value("relay", "iMessage 转发", "未开启")
        self._add_value("recent", "最近转发", "—")
        self._menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add_action("重新检测模块", "rescan:")
        self._add_action("设置…", "showSettings:", ",")
        self._menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add_action("退出 4G Bridge", "quit:", "q")

    def _add_value(self, key: str, label: str, value: str) -> None:
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"{label}  {value}", None, ""
        )
        item.setEnabled_(False)
        item.setRepresentedObject_(label)
        self._menu.addItem_(item)
        self._values[key] = item

    def _add_action(self, title: str, action: str, key: str = "") -> None:
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        item.setTarget_(self)
        self._menu.addItem_(item)

    @objc.python_method
    def update_(self, snapshot: ModemSnapshot) -> None:
        button = self._status_item.button()
        if snapshot.device_state == DeviceState.MISSING:
            symbol = "antenna.radiowaves.left.and.right.slash"
            button.setTitle_("")
        elif snapshot.data_state == DataState.ON:
            symbol = "chart.bar.fill"
            button.setTitle_(" 4G")
        elif snapshot.data_state == DataState.PROTECTION_FAILED:
            symbol = "exclamationmark.triangle.fill"
            button.setTitle_("")
        else:
            symbol = "antenna.radiowaves.left.and.right"
            button.setTitle_("")
        image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            symbol, "4G Bridge 状态"
        )
        image.setTemplate_(True)
        button.setImage_(image)
        self._set("device", "已连接" if snapshot.descriptor else "未连接")
        descriptor = snapshot.descriptor
        self._set(
            "usb",
            f"{descriptor.vendor_id:04X}:{descriptor.product_id:04X}" if descriptor else "—",
        )
        self._set("operator", snapshot.operator or "—")
        self._set("sim", snapshot.sim_state.value.upper())
        self._set("signal", f"{snapshot.rssi_dbm} dBm" if snapshot.rssi_dbm is not None else "—")
        self._set("registration", snapshot.registration.value)
        self._set("rat", snapshot.rat or "—")
        self._set("interface", snapshot.interface or "—")
        self._set("ip", snapshot.ipv4 or "—")
        self._set("gateway", snapshot.gateway or "—")
        self._set("default", snapshot.default_interface or "—")
        self._set("vpn", "已连接" if snapshot.vpn_active else "未连接")
        self._values["data"].setTitle_(
            "关闭 4G 数据" if snapshot.data_state == DataState.ON else "开启 4G 数据…"
        )

    @objc.python_method
    def setRelayStatus_recent_(self, enabled: bool, recent: str | None) -> None:
        self._set("relay", "✓ 已开启" if enabled else "未开启")
        self._set("recent", recent or "—")

    @objc.python_method
    def setTrafficSnapshot_usage_(self, snapshot, usage) -> None:
        if snapshot is None:
            for key in ("download", "upload", "session", "traffic", "month"):
                self._set(key, "—")
            return
        self._set("download", f"{_format_bytes(snapshot.download_bps)}/s")
        self._set("upload", f"{_format_bytes(snapshot.upload_bps)}/s")
        self._set("session", _format_bytes(snapshot.session_rx_bytes + snapshot.session_tx_bytes))
        self._set("traffic", _format_bytes(usage.today_rx + usage.today_tx))
        self._set("month", _format_bytes(usage.month_rx + usage.month_tx))

    def _set(self, key: str, value: str) -> None:
        item = self._values[key]
        label = str(item.representedObject())
        item.setTitle_(f"{label}  {value}")

    @objc.IBAction
    def toggleData_(self, _sender):
        self._delegate.toggle_data()

    @objc.IBAction
    def rescan_(self, _sender):
        self._delegate.rescan()

    @objc.IBAction
    def showSettings_(self, _sender):
        self._delegate.show_settings()

    @objc.IBAction
    def quit_(self, _sender):
        self._delegate.quit()


def _format_bytes(value: float | int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return "0 B"
