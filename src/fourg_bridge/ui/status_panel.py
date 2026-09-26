"""Native transient menu-bar quick controls, with no duplicated device logic."""

from __future__ import annotations

import AppKit
import objc

from fourg_bridge.models import DataState
from fourg_bridge.support.presentation import connection_title, format_bytes, operator_name
from fourg_bridge.ui.components import group, label, pin, section_title, stack, symbol


class StatusPanelController(AppKit.NSViewController):
    def initWithDelegate_(self, delegate):
        self = objc.super(StatusPanelController, self).init()
        if self is None:
            return None
        self._delegate = delegate
        view = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 380, 510))
        self.setView_(view)
        self._title = label("连接你的 4G 模块", 19, weight=AppKit.NSFontWeightSemibold)
        self._subtitle = label("接入模块后自动检测", 12, True)
        self._data = AppKit.NSButton.buttonWithTitle_target_action_(
            "开启 4G 数据…", self, "toggleData:"
        )
        self._warning = label("Wi-Fi 优先 · 数据默认关闭", 11, True)
        self._today = label("—", 25, numeric=True, weight=AppKit.NSFontWeightSemibold)
        self._speed = label("↓ —    ↑ —", 12, True, numeric=True)
        self._relay = label("未开启", 13)
        self._recent = label("本次运行暂无转发", 11, True)
        content = stack(
            [
                stack(
                    [
                        symbol("antenna.radiowaves.left.and.right", 20),
                        label("4G Bridge", 15, weight=AppKit.NSFontWeightSemibold),
                    ],
                    True,
                    10,
                ),
                group([self._title, self._subtitle, self._data, self._warning]),
                group([section_title("今日流量", "chart.bar"), self._today, self._speed]),
                group([section_title("iMessage 转发", "message"), self._relay, self._recent]),
                AppKit.NSButton.buttonWithTitle_target_action_(
                    "打开连接总览…", self, "showOverview:"
                ),
            ],
            spacing=12,
        )
        pin(content, view, 18)
        for child in content.arrangedSubviews():
            child.widthAnchor().constraintEqualToAnchor_(content.widthAnchor()).setActive_(True)
        return self

    @objc.python_method
    def refresh(self, snapshot):
        self._title.setStringValue_(connection_title(snapshot))
        self._subtitle.setStringValue_(
            f"{operator_name(snapshot.operator)} · {snapshot.rssi_dbm} dBm"
            if snapshot.rssi_dbm is not None
            else "等待模块与信号信息"
        )
        state = snapshot.data_state
        self._data.setTitle_("关闭 4G 数据" if state == DataState.ON else "开启 4G 数据…")
        self._data.setEnabled_(
            snapshot.descriptor is not None
            and state not in (DataState.ENABLING, DataState.DISABLING)
        )
        self._warning.setStringValue_(snapshot.warning or "Wi-Fi 优先 · 不自动开启 SIM 数据")
        sample, usage = self._delegate.traffic_state()
        self._today.setStringValue_(format_bytes(usage.today_rx + usage.today_tx))
        self._speed.setStringValue_(
            f"↓ {format_bytes(sample.download_bps)}/s    ↑ {format_bytes(sample.upload_bps)}/s"
            if sample
            else "↓ —    ↑ —    等待网卡采样"
        )
        self._relay.setStringValue_("已开启" if self._delegate.relay_enabled() else "未开启")
        self._recent.setStringValue_(self._delegate.recent_relay() or "本次运行暂无转发")
        if getattr(self._delegate, "diagnostic_mode", False):
            self._title.setStringValue_("短信测试模式")
            self._subtitle.setStringValue_("模块检测已暂停，并非 USB 未连接")
            self._data.setTitle_("恢复模块控制…")
            self._data.setEnabled_(True)
            self._warning.setStringValue_("恢复后先关闭数据；短信转发保持关闭。")
            self._relay.setStringValue_("测试模式中暂停")

    @objc.IBAction
    def toggleData_(self, _sender):
        self._popover.performClose_(None)
        self._delegate.toggle_data()

    @objc.IBAction
    def showOverview_(self, _sender):
        self._popover.performClose_(None)
        self._delegate.show_overview()
