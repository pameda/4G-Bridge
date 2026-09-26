"""Native transient menu-bar quick controls, with no duplicated device logic."""

from __future__ import annotations

import AppKit
import objc

from fourg_bridge.models import DataState
from fourg_bridge.support.presentation import connection_title, format_bytes, operator_name
from fourg_bridge.ui.app_network import AppNetworkTable
from fourg_bridge.ui.components import group, label, pin, section_title, stack, symbol
from fourg_bridge.ui.usage_ring import UsageRing


class PanelDocument(AppKit.NSView):
    def isFlipped(self):
        return True


class StatusPanelController(AppKit.NSViewController):
    def initWithDelegate_(self, delegate):
        self = objc.super(StatusPanelController, self).init()
        if self is None:
            return None
        self._delegate = delegate
        view = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 380, 740))
        self.setView_(view)
        self._title = label("连接你的 4G 模块", 19, weight=AppKit.NSFontWeightSemibold)
        self._subtitle = label("接入模块后自动检测", 12, True)
        self._data = AppKit.NSButton.buttonWithTitle_target_action_(
            "开启 4G 数据…", self, "toggleData:"
        )
        self._warning = label("Wi-Fi 优先 · 数据默认关闭", 11, True)
        self._today = label("—", 25, numeric=True, weight=AppKit.NSFontWeightSemibold)
        self._speed = label("↓ —    ↑ —", 12, True, numeric=True)
        self._ring = UsageRing.alloc().init()
        self._plan_used = label("已用 —", 13, numeric=True)
        self._plan_total = label("总量 —", 12, True, numeric=True)
        self._plan_updated = label("等待运营商查询", 10, True)
        self._relay = label("未开启", 13)
        self._recent = label("本次运行暂无转发", 11, True)
        self._app_table = AppNetworkTable.alloc().initWithCompact_(True)
        self._app_status = label("打开后开始观测", 11, True)
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
                group(
                    [
                        section_title("运营商套餐", "chart.pie"),
                        stack(
                            [
                                self._ring,
                                stack(
                                    [self._plan_used, self._plan_total, self._plan_updated],
                                    spacing=5,
                                ),
                            ],
                            True,
                            16,
                        ),
                        self._today,
                        self._speed,
                    ]
                ),
                group([section_title("iMessage 转发", "message"), self._relay, self._recent]),
                group(
                    [
                        section_title("应用网络", "network"),
                        self._app_table.view,
                        self._app_status,
                        AppKit.NSButton.buttonWithTitle_target_action_(
                            "查看全部应用…", self, "showAppNetwork:"
                        ),
                    ]
                ),
                AppKit.NSButton.buttonWithTitle_target_action_(
                    "打开连接总览…", self, "showOverview:"
                ),
            ],
            spacing=12,
        )
        scroll = AppKit.NSScrollView.alloc().init()
        scroll.setDrawsBackground_(False)
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        document = PanelDocument.alloc().init()
        document.setTranslatesAutoresizingMaskIntoConstraints_(False)
        scroll.setDocumentView_(document)
        pin(scroll, view, 0)
        document.widthAnchor().constraintEqualToAnchor_(
            scroll.contentView().widthAnchor()
        ).setActive_(True)
        pin(content, document, 18)
        for child in content.arrangedSubviews():
            child.widthAnchor().constraintEqualToAnchor_(content.widthAnchor()).setActive_(True)
        return self

    @objc.python_method
    def refresh(self, snapshot):
        usage = self._delegate.carrier_usage()
        self._ring.update(usage)
        self._plan_used.setStringValue_(
            f"已用 {format_bytes(usage.used_bytes)}" if usage else "已用 —"
        )
        self._plan_total.setStringValue_(
            f"总量 {format_bytes(usage.total_bytes)}" if usage else "总量 —"
        )
        self._plan_updated.setStringValue_(
            usage.basis + "\n" + usage.timestamp.astimezone().strftime("短信更新 %m-%d %H:%M")
            if usage
            else "未识别完整套餐 · 不估算"
        )
        rows, _status, paused = self._delegate.app_network_state()
        self._app_table.update(rows)
        self._app_status.setStringValue_(
            "观测已暂停" if paused else "全网络进程汇总 · 前 3 项 · 非 4G 用量" if rows else _status
        )
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
        self._warning.setStringValue_(
            snapshot.warning
            or (
                "Wi-Fi 优先 · 自动接管已授权，受流量保护"
                if self._delegate.data_policy()[0].auto_data_enabled
                else "Wi-Fi 优先 · 自动接管未开启"
            )
        )
        sample, usage = self._delegate.traffic_state()
        self._today.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        self._today.setStringValue_("本机今日 " + format_bytes(usage.today_rx + usage.today_tx))
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
            self._warning.setStringValue_("恢复后先关闭数据；短信转发遵循已保存设置。")
            self._relay.setStringValue_("测试模式中暂停")

    @objc.IBAction
    def showAppNetwork_(self, _sender):
        self._popover.performClose_(None)
        self._delegate.show_app_network()

    @objc.IBAction
    def toggleData_(self, _sender):
        self._popover.performClose_(None)
        self._delegate.toggle_data()

    @objc.IBAction
    def showOverview_(self, _sender):
        self._popover.performClose_(None)
        self._delegate.show_overview()
