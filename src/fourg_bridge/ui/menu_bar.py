from __future__ import annotations

import AppKit
import objc

from fourg_bridge.models import DataState, ModemSnapshot
from fourg_bridge.support.presentation import format_bytes as _format_bytes
from fourg_bridge.support.status_item import status_item_style
from fourg_bridge.ui.status_badge import STATUS_ITEM_WIDTH, make_status_badge
from fourg_bridge.ui.status_panel import StatusPanelController


class MenuBarController(AppKit.NSObject):
    def initWithDelegate_(self, delegate: object):
        self = objc.super(MenuBarController, self).init()
        if self is None:
            return None
        self._delegate = delegate
        self._status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            STATUS_ITEM_WIDTH
        )
        self._badge_style = None
        self._menu = AppKit.NSMenu.alloc().initWithTitle_("4G Bridge")
        self._panel = StatusPanelController.alloc().initWithDelegate_(delegate)
        self._popover = AppKit.NSPopover.alloc().init()
        self._popover.setContentViewController_(self._panel)
        self._popover.setBehavior_(AppKit.NSPopoverBehaviorTransient)
        self._popover.setContentSize_(AppKit.NSMakeSize(380, 510))
        self._panel._popover = self._popover
        button = self._status_item.button()
        button.setTitle_("")
        button.setImagePosition_(AppKit.NSImageOnly)
        button.setImageScaling_(AppKit.NSImageScaleProportionallyDown)
        button.setTarget_(self)
        button.setAction_("statusClicked:")
        button.sendActionOn_(AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp)
        self._values: dict[str, AppKit.NSMenuItem] = {}
        self._build_menu()
        self.update_(ModemSnapshot())
        return self

    def _build_menu(self) -> None:
        self._menu.setAutoenablesItems_(False)
        heading = AppKit.NSMenuItem.sectionHeaderWithTitle_("4G Bridge")
        self._menu.addItem_(heading)
        self._add_action("打开连接总览…", "showOverview:")
        self._add_value("device", "QDC507", "未连接")
        self._add_value("operator", "运营商", "—")
        self._add_value("signal", "信号", "—")
        self._menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add_value("connection", "4G 数据", "已关闭")
        data = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "开启 4G 数据…", "toggleData:", ""
        )
        data.setTarget_(self)
        self._menu.addItem_(data)
        self._values["data"] = data
        self._add_value("traffic", "今日流量", "—")
        self._menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add_value("relay", "短信转发", "未开启")
        self._add_value("recent", "最近转发", "—")
        self._menu.addItem_(AppKit.NSMenuItem.separatorItem())
        parent = self._menu
        detail_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "连接详情", None, ""
        )
        detail_menu = AppKit.NSMenu.alloc().initWithTitle_("连接详情")
        detail_menu.setAutoenablesItems_(False)
        detail_item.setSubmenu_(detail_menu)
        parent.addItem_(detail_item)
        self._menu = detail_menu
        self._add_value("usb", "USB", "—")
        self._add_value("sim", "SIM", "未知")
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
        self._add_value("month", "本月流量", "—")
        self._menu = parent
        self._add_action("设置…", "showSettings:", ",")
        self._add_action("重新检测模块", "rescan:")
        self._menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add_action("退出 4G Bridge", "quit:", "q")

    @objc.python_method
    def _add_value(self, key: str, label: str, value: str) -> None:
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"{label}  {value}", None, ""
        )
        item.setEnabled_(False)
        item.setRepresentedObject_(label)
        self._menu.addItem_(item)
        self._values[key] = item

    @objc.python_method
    def _add_action(self, title: str, action: str, key: str = "") -> None:
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        item.setTarget_(self)
        self._menu.addItem_(item)

    @objc.python_method
    def update_(self, snapshot: ModemSnapshot) -> None:
        self._panel.refresh(snapshot)
        button = self._status_item.button()
        style = status_item_style(snapshot)
        if style != self._badge_style:
            button.setImage_(make_status_badge(style))
            self._badge_style = style
        button.setAccessibilityLabel_("4G Bridge · " + style.description)
        self._set("device", "已连接" if snapshot.descriptor else "未连接")
        descriptor = snapshot.descriptor
        self._set(
            "usb",
            f"{descriptor.vendor_id:04X}:{descriptor.product_id:04X}" if descriptor else "—",
        )
        self._set(
            "operator",
            {"CHN-CT": "中国电信", "CHINA MOBILE": "中国移动", "CHN-UNICOM": "中国联通"}.get(
                snapshot.operator, snapshot.operator or "—"
            ),
        )
        self._set(
            "sim",
            {
                "ready": "已就绪",
                "missing": "未插卡",
                "not_ready": "未就绪",
                "pin_required": "需要 PIN",
            }.get(snapshot.sim_state.value, "未知"),
        )
        self._set("signal", f"{snapshot.rssi_dbm} dBm" if snapshot.rssi_dbm is not None else "—")
        self._set(
            "registration",
            {
                "registered_home": "已注册",
                "registered_roaming": "漫游",
                "searching": "搜索中",
                "denied": "注册被拒绝",
                "not_registered": "未注册",
            }.get(snapshot.registration.value, "未知"),
        )
        self._set("rat", snapshot.rat or "—")
        self._set("interface", snapshot.interface or "—")
        self._set("ip", snapshot.ipv4 or "—")
        self._set("gateway", snapshot.gateway or "—")
        self._set("default", snapshot.default_interface or "—")
        self._set("vpn", "已连接" if snapshot.vpn_active else "未连接")
        self._values["data"].setTitle_(
            "关闭 4G 数据" if snapshot.data_state == DataState.ON else "开启 4G 数据…"
        )
        state = snapshot.data_state
        self._set(
            "connection",
            {
                DataState.OFF: "已关闭",
                DataState.ON: "已开启 · Wi-Fi 优先",
                DataState.ENABLING: "正在连接…",
                DataState.DISABLING: "正在关闭…",
                DataState.PROTECTION_FAILED: "保护失败",
            }[state],
        )
        self._values["data"].setEnabled_(
            snapshot.descriptor is not None
            and state not in (DataState.ENABLING, DataState.DISABLING)
        )
        button.setToolTip_("4G Bridge · " + (snapshot.warning or style.description))
        if getattr(self._delegate, "diagnostic_mode", False):
            self._set("device", "测试模式 · 未执行检测")
            self._set("connection", "控制已暂停")
            self._values["data"].setTitle_("恢复模块控制…")
            self._values["data"].setEnabled_(True)
            button.setToolTip_("4G Bridge · 短信测试模式，模块检测已暂停")
            button.setAccessibilityLabel_("4G Bridge · 短信测试模式，模块检测已暂停")

    @objc.python_method
    def setRelayStatus_recent_(self, enabled: bool, recent: str | None) -> None:
        self._set("relay", "✓ 已开启" if enabled else "未开启")
        self._set("recent", recent or "—")

    @objc.IBAction
    def statusClicked_(self, _sender):
        event = AppKit.NSApp.currentEvent()
        if event and event.type() == AppKit.NSEventTypeRightMouseUp:
            self._popover.performClose_(None)
            self._status_item.popUpStatusItemMenu_(self._menu)
        elif self._popover.isShown():
            self._popover.performClose_(None)
        else:
            self._panel.refresh(self._delegate.current_snapshot())
            button = self._status_item.button()
            self._popover.showRelativeToRect_ofView_preferredEdge_(
                button.bounds(), button, AppKit.NSMinYEdge
            )

    @objc.python_method
    def setTrafficSnapshot_usage_(self, snapshot, usage) -> None:
        self._set("traffic", _format_bytes(usage.today_rx + usage.today_tx))
        self._set("month", _format_bytes(usage.month_rx + usage.month_tx))
        if snapshot is None:
            for key in ("download", "upload", "session"):
                self._set(key, "—")
            return
        self._set("download", f"{_format_bytes(snapshot.download_bps)}/s")
        self._set("upload", f"{_format_bytes(snapshot.upload_bps)}/s")
        self._set("session", _format_bytes(snapshot.session_rx_bytes + snapshot.session_tx_bytes))
        self._set("traffic", _format_bytes(usage.today_rx + usage.today_tx))
        self._set("month", _format_bytes(usage.month_rx + usage.month_tx))

    @objc.python_method
    def _set(self, key: str, value: str) -> None:
        item = self._values[key]
        label = str(item.representedObject())
        item.setTitle_(f"{label}  {value}")

    @objc.IBAction
    def toggleData_(self, _sender):
        self._delegate.toggle_data()

    @objc.IBAction
    def rescan_(self, _sender):
        self._delegate.redetect()

    @objc.IBAction
    def showSettings_(self, _sender):
        self._delegate.show_settings()

    @objc.IBAction
    def showOverview_(self, _sender):
        self._delegate.show_overview()

    @objc.IBAction
    def quit_(self, _sender):
        self._delegate.quit()
