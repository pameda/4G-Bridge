from __future__ import annotations

import AppKit
import objc

from fourg_bridge import __version__
from fourg_bridge.models import DataState, DeviceState
from fourg_bridge.support.presentation import (
    SpeedHistory,
    connection_title,
    format_bytes,
    operator_name,
    route_description,
)
from fourg_bridge.ui.components import (
    SpeedChart,
    columns,
    group,
    label,
    page,
    section_title,
    stack,
    symbol,
)


class SettingsWindowController(AppKit.NSWindowController):
    def initWithDelegate_(self, delegate):
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, 820, 670),
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self = objc.super(SettingsWindowController, self).initWithWindow_(window)
        if self is None:
            return None
        self._delegate = delegate
        self._history = SpeedHistory()
        self._metrics = {}
        self._details = {}
        window.setTitle_("4G Bridge")
        window.setReleasedWhenClosed_(False)
        window.setBackgroundColor_(AppKit.NSColor.windowBackgroundColor())
        self._tabs = AppKit.NSTabViewController.alloc().init()
        self._tabs.setTabStyle_(AppKit.NSTabViewControllerTabStyleToolbar)
        self._tabs.setTransitionOptions_(0)
        for title, icon, view in (
            ("总览", "square.grid.2x2", self._overview_page()),
            ("流量", "chart.xyaxis.line", self._traffic_page()),
            ("短信转发", "message", self._relay_page()),
            ("设备", "antenna.radiowaves.left.and.right", self._device_page()),
            ("设置", "gearshape", self._preferences_page()),
        ):
            controller = AppKit.NSViewController.alloc().init()
            controller.setView_(view)
            controller.setTitle_(title)
            item = AppKit.NSTabViewItem.tabViewItemWithViewController_(controller)
            item.setLabel_(title)
            item.setImage_(
                AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(icon, title)
            )
            self._tabs.addTabViewItem_(item)
        window.setContentViewController_(self._tabs)
        window.setToolbarStyle_(AppKit.NSWindowToolbarStylePreference)
        window.setContentSize_(AppKit.NSMakeSize(820, 650))
        window.center()
        return self

    @objc.python_method
    def _button(self, title, action):
        return AppKit.NSButton.buttonWithTitle_target_action_(title, self, action)

    @objc.python_method
    def _metric(self, key, title, icon, note):
        value = label("—", 27, weight=AppKit.NSFontWeightSemibold, numeric=True)
        self._metrics[key] = value
        return group([section_title(title, icon), value, label(note, 11, True)])

    @objc.python_method
    def _rows(self, fields):
        rows = []
        for key, title in fields:
            caption = label(title, 12, True)
            caption.widthAnchor().constraintEqualToConstant_(86).setActive_(True)
            value = label("—", 12)
            value.setSelectable_(True)
            self._details[key] = value
            rows.append(stack([caption, value], True, 8))
        return stack(rows, spacing=9)

    @objc.python_method
    def _overview_page(self):
        self._connection = label("连接你的 4G 模块", 23, weight=AppKit.NSFontWeightSemibold)
        self._connection_detail = label("接入 QDC507 后，即可查看蜂窝网络状态。", 13, True)
        self._network_status = label("数据默认关闭，仅在你主动开启后使用 SIM 流量。", 12, True)
        self._data_button = self._button("开启 4G 数据…", "toggleData:")
        self._data_button.setBezelColor_(AppKit.NSColor.controlAccentColor())
        self._rescan = self._button("重新检测", "rescan:")
        self._hero_symbol = symbol("antenna.radiowaves.left.and.right", 46)
        hero = group(
            [
                stack(
                    [
                        self._hero_symbol,
                        stack([self._connection, self._connection_detail], spacing=6),
                    ],
                    True,
                    20,
                ),
                stack([self._data_button, self._rescan, label("Wi-Fi 优先", 12, True)], True),
                self._network_status,
            ]
        )
        self._overview_relay = label("未开启", 18, weight=AppKit.NSFontWeightMedium)
        self._recent = label("尚无转发记录", 12, True)
        self._route = label("尚未取得系统默认接口", 12, True)
        return page(
            "连接总览",
            "蜂窝连接与短信转发，一目了然。",
            [
                hero,
                columns(
                    [
                        self._metric("today", "今日流量", "chart.bar", "本机累计 · 下载 + 上传"),
                        self._metric("download", "下载速度", "arrow.down", "QDC507 网卡实时采样"),
                        self._metric("upload", "上传速度", "arrow.up", "QDC507 网卡实时采样"),
                    ]
                ),
                columns(
                    [
                        group(
                            [
                                section_title("蜂窝网络", "antenna.radiowaves.left.and.right"),
                                self._rows(
                                    (
                                        ("operator", "运营商"),
                                        ("signal", "信号"),
                                        ("interface", "网络接口"),
                                    )
                                ),
                                self._route,
                            ]
                        ),
                        group(
                            [
                                section_title("iMessage 转发", "message"),
                                self._overview_relay,
                                self._recent,
                                self._button("管理短信转发", "showRelay:"),
                            ]
                        ),
                    ]
                ),
            ],
        )

    @objc.python_method
    def _traffic_page(self):
        self._chart = SpeedChart.alloc().init()
        self._chart_note = label("等待网卡采样", 11, True)
        self._traffic_breakdown = label("等待流量统计", 12, True, numeric=True)
        graph = group(
            [
                section_title("速度趋势", "waveform.path"),
                label("↓ 下载（蓝色）    ↑ 上传（青色）", 12, True),
                self._chart,
                self._chart_note,
            ]
        )
        self._chart.widthAnchor().constraintEqualToAnchor_constant_(
            graph.widthAnchor(), -40
        ).setActive_(True)
        return page(
            "流量",
            "只统计 QDC507 网卡，不分析你的上网内容。",
            [
                columns(
                    [
                        self._metric("session", "本次连接", "timer", "当前连接期间累计"),
                        self._metric("traffic_today", "今日累计", "sun.max", "按本机日期统计"),
                        self._metric("month", "本月累计", "calendar", "按自然月统计"),
                    ]
                ),
                graph,
                group(
                    [
                        section_title("统计口径", "info.circle"),
                        self._traffic_breakdown,
                        label(
                            "仅统计应用运行期间观测到的网卡流量，不代表运营商账单或套餐剩余量。"
                            "应用退出期间的用量不会补算。",
                            12,
                            True,
                        ),
                    ]
                ),
            ],
        )

    @objc.python_method
    def _relay_page(self):
        self._enabled = AppKit.NSSwitch.alloc().init()
        self._enabled.setTarget_(self)
        self._enabled.setAction_("relayChanged:")
        self._enabled.setAccessibilityLabel_("iMessage 转发")
        self._target = AppKit.NSTextField.alloc().init()
        self._target.setPlaceholderString_("+国家区号手机号 / iMessage 邮箱")
        self._target.setAccessibilityLabel_("转发目标")
        self._target.widthAnchor().constraintEqualToConstant_(540).setActive_(True)
        self._target.setFont_(AppKit.NSFont.systemFontOfSize_(14))
        self._queue_info = label("转发队列正常", 12, True)
        self._bridge_status = label("尚未检查 iMessage", 12, True)
        self._check_button = self._button("检查连接", "checkMessages:")
        self._test_button = self._button("发送测试消息…", "sendTest:")
        return page(
            "短信转发",
            "短信进入“信息”，正文不留在这里。",
            [
                group(
                    [
                        stack(
                            [
                                symbol("message.fill", 32, AppKit.NSColor.systemGreenColor()),
                                stack(
                                    [
                                        label(
                                            "转发到 iMessage",
                                            17,
                                            weight=AppKit.NSFontWeightSemibold,
                                        ),
                                        label("QDC507 收到短信后，发送到你指定的会话。", 12, True),
                                    ],
                                    spacing=5,
                                ),
                                self._enabled,
                            ],
                            True,
                            16,
                        )
                    ]
                ),
                group(
                    [
                        section_title("接收目标", "person.crop.circle"),
                        self._target,
                        stack(
                            [
                                self._button("保存目标", "saveTarget:"),
                                self._check_button,
                                self._test_button,
                            ],
                            True,
                        ),
                        self._bridge_status,
                    ]
                ),
                group(
                    [
                        section_title("处理状态", "checkmark.shield"),
                        self._queue_info,
                        label("投递不确定时，请先在“信息”中核对，再选择重发或确认。", 12, True),
                        stack(
                            [
                                self._button("重新发送不确定项…", "retryUnknown:"),
                                self._button("确认已发送…", "confirmUnknown:"),
                            ],
                            True,
                        ),
                    ]
                ),
                label(
                    "请先登录 iMessage。目标保存在钥匙串；成功接受发送请求后才清理模块短信。",
                    12,
                    True,
                ),
            ],
        )

    @objc.python_method
    def _device_page(self):
        self._device_status = label("等待连接模块", 14, weight=AppKit.NSFontWeightSemibold)
        self._device_warning = label("仅显示本机检测结果，不执行联网探测。", 12, True)
        return page(
            "设备与网络",
            "连接诊断与接口详情。",
            [
                group(
                    [
                        section_title("QDC507", "externaldrive.connected.to.line.below"),
                        self._device_status,
                        self._device_warning,
                    ]
                ),
                columns(
                    [
                        group(
                            [
                                section_title("蜂窝模块", "simcard"),
                                self._rows(
                                    (
                                        ("usb", "USB VID/PID"),
                                        ("device_operator", "运营商"),
                                        ("sim", "SIM 状态"),
                                        ("registration", "网络注册"),
                                        ("rat", "无线制式"),
                                        ("rssi", "信号强度"),
                                    )
                                ),
                            ]
                        ),
                        group(
                            [
                                section_title("macOS 网络", "network"),
                                self._rows(
                                    (
                                        ("device_interface", "ECM 接口"),
                                        ("service", "网络服务"),
                                        ("ipv4", "IPv4"),
                                        ("gateway", "网关"),
                                        ("default", "默认接口"),
                                        ("vpn", "VPN"),
                                    )
                                ),
                            ]
                        ),
                    ]
                ),
                group(
                    [
                        section_title("安全连接", "lock.shield"),
                        label(
                            "Wi-Fi 优先；保留现有 VPN 和 DNS 配置。\n"
                            "启动、重新检测、拔插、睡眠／唤醒和退出后，4G 数据保持关闭。",
                            12,
                            True,
                        ),
                        self._button("重新检测模块", "rescan:"),
                    ]
                ),
            ],
        )

    @objc.python_method
    def _preferences_page(self):
        self._appearance = (
            AppKit.NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
                ["跟随系统", "浅色", "深色"],
                AppKit.NSSegmentSwitchTrackingSelectOne,
                self,
                "appearanceChanged:",
            )
        )
        self._appearance.setAccessibilityLabel_("界面外观")
        return page(
            "设置",
            "为 Mac 而设计，隐私留在本机。",
            [
                group(
                    [
                        section_title("外观", "circle.lefthalf.filled"),
                        self._appearance,
                        label("使用 macOS 系统字体、语义色和原生控件。", 12, True),
                    ]
                ),
                group(
                    [
                        section_title("隐私保护", "hand.raised"),
                        label(
                            "短信正文不写入数据库或普通日志，诊断号码自动脱敏。\n"
                            "不访问 Messages 数据库，不申请辅助功能或完全磁盘访问。\n"
                            "不抓包，不记录域名，也不统计应用级流量。",
                            13,
                            True,
                        ),
                    ]
                ),
                group(
                    [
                        stack(
                            [
                                symbol("antenna.radiowaves.left.and.right", 32),
                                stack(
                                    [
                                        label("4G Bridge", 20, weight=AppKit.NSFontWeightSemibold),
                                        label(
                                            f"版本 {__version__} · Apple Silicon · QDC507", 12, True
                                        ),
                                    ],
                                    spacing=5,
                                ),
                            ],
                            True,
                            16,
                        ),
                        label("本机运行 · 无云服务器 · 默认关闭 SIM 数据", 12, True),
                    ]
                ),
            ],
        )

    @objc.python_method
    def refresh(self, include_target=True):
        self._enabled.setState_(int(self._delegate.relay_enabled()))
        if include_target:
            self._loaded_target = self._delegate.relay_target() or ""
            self._target.setStringValue_(self._loaded_target)
        busy, bridge_status = self._delegate.bridge_status()
        self._bridge_status.setStringValue_(bridge_status)
        self._check_button.setEnabled_(not busy)
        self._test_button.setEnabled_(not busy)
        snapshot = self._delegate.current_snapshot()
        state = snapshot.data_state
        self._connection.setStringValue_(connection_title(snapshot))
        self._connection_detail.setStringValue_(
            f"QDC507 · {operator_name(snapshot.operator)} · {snapshot.rat or '等待网络注册'}"
            if snapshot.descriptor
            else "接入 QDC507 后，即可查看蜂窝网络状态。"
        )
        status = {
            DataState.OFF: "数据已关闭，开启前会再次确认。短信转发可独立工作。",
            DataState.ON: "Wi-Fi 可用时优先使用；VPN 开启时由现有 VPN 管理路由。",
            DataState.ENABLING: "正在检查网络，必要时重启模块一次。可能需要约两分钟。",
            DataState.DISABLING: "正在关闭 4G 数据，请稍候。",
            DataState.PROTECTION_FAILED: "无法确认数据已关闭，请断开模块并检查。",
        }[state]
        self._network_status.setStringValue_(snapshot.warning or status)
        problem = bool(snapshot.warning) or state == DataState.PROTECTION_FAILED
        self._network_status.setTextColor_(
            AppKit.NSColor.systemOrangeColor() if problem else AppKit.NSColor.secondaryLabelColor()
        )
        self._hero_symbol.setContentTintColor_(
            AppKit.NSColor.systemOrangeColor()
            if problem
            else AppKit.NSColor.controlAccentColor()
            if state == DataState.ON
            else AppKit.NSColor.secondaryLabelColor()
        )
        self._data_button.setTitle_("关闭 4G 数据" if state == DataState.ON else "开启 4G 数据…")
        busy = state in (DataState.ENABLING, DataState.DISABLING)
        self._data_button.setEnabled_(snapshot.descriptor is not None and not busy)
        self._rescan.setEnabled_(not busy)
        signal = f"{snapshot.rssi_dbm} dBm" if snapshot.rssi_dbm is not None else "未取得"
        registration = {
            "registered_home": "已注册",
            "registered_roaming": "已注册 · 漫游",
            "searching": "搜索中",
            "denied": "注册被拒绝",
            "not_registered": "未注册",
        }.get(snapshot.registration.value, "等待查询")
        descriptor = snapshot.descriptor
        values = {
            "operator": operator_name(snapshot.operator),
            "device_operator": operator_name(snapshot.operator),
            "signal": signal,
            "rssi": signal,
            "interface": snapshot.interface or "未发现",
            "device_interface": snapshot.interface or "未发现",
            "usb": f"{descriptor.vendor_id:04X}:{descriptor.product_id:04X}"
            if descriptor
            else "未发现",
            "sim": {
                "ready": "已就绪",
                "missing": "未插卡",
                "not_ready": "未就绪",
                "pin_required": "需要 PIN",
            }.get(snapshot.sim_state.value, "等待查询"),
            "registration": registration,
            "rat": snapshot.rat or "等待查询",
            "service": snapshot.network_service or "未发现",
            "ipv4": snapshot.ipv4 or "未分配",
            "gateway": snapshot.gateway or "未取得",
            "default": snapshot.default_interface or "未取得",
            "vpn": "已连接" if snapshot.vpn_active else "未检测到",
        }
        for key, value in values.items():
            self._details[key].setStringValue_(value)
        self._route.setStringValue_(route_description(snapshot))
        self._device_status.setStringValue_(
            "模块读取异常"
            if snapshot.device_state == DeviceState.ERROR
            else "USB 模块已连接"
            if descriptor
            else "等待连接模块"
        )
        self._device_warning.setStringValue_(
            snapshot.warning or "仅显示本机检测结果，不执行联网探测。"
        )
        self._overview_relay.setStringValue_(
            "已开启" if self._delegate.relay_enabled() else "未开启"
        )
        self._recent.setStringValue_(self._delegate.recent_relay() or "尚无转发记录")
        self._queue_info.setStringValue_(self._delegate.relay_queue_summary())
        self._appearance.setSelectedSegment_(
            ("system", "light", "dark").index(self._delegate.appearance())
        )
        self._refresh_traffic()

    @objc.python_method
    def _refresh_traffic(self):
        sample, usage = self._delegate.traffic_state()
        self._history.add(sample)
        self._chart.update(self._history)
        values = {
            "today": format_bytes(usage.today_rx + usage.today_tx),
            "traffic_today": format_bytes(usage.today_rx + usage.today_tx),
            "month": format_bytes(usage.month_rx + usage.month_tx),
            "session": format_bytes(sample.session_rx_bytes + sample.session_tx_bytes)
            if sample
            else "—",
            "download": f"{format_bytes(sample.download_bps)}/s" if sample else "—",
            "upload": f"{format_bytes(sample.upload_bps)}/s" if sample else "—",
        }
        for key, value in values.items():
            self._metrics[key].setStringValue_(value)
        count = len(self._history.samples)
        self._chart_note.setStringValue_(
            f"{sample.interface} · 最近 {count} 次采样 · 更新于 {sample.sampled_at:%H:%M:%S}"
            if sample
            else "暂无网卡采样；连接模块后自动显示，不主动产生流量。"
        )
        self._traffic_breakdown.setStringValue_(
            f"今日  ↓ {format_bytes(usage.today_rx)}  ↑ {format_bytes(usage.today_tx)}     "
            f"本月  ↓ {format_bytes(usage.month_rx)}  ↑ {format_bytes(usage.month_tx)}"
        )

    @objc.IBAction
    def toggleData_(self, _sender):
        self._delegate.toggle_data()

    @objc.IBAction
    def rescan_(self, _sender):
        self._delegate.redetect()

    @objc.IBAction
    def showRelay_(self, _sender):
        self._tabs.setSelectedTabViewItemIndex_(2)

    @objc.IBAction
    def appearanceChanged_(self, _sender):
        self._delegate.set_appearance(
            ("system", "light", "dark")[self._appearance.selectedSegment()]
        )

    @objc.IBAction
    def relayChanged_(self, _sender):
        self._delegate.set_relay_enabled(self._enabled.state() == AppKit.NSControlStateValueOn)
        self.refresh(False)

    @objc.IBAction
    def saveTarget_(self, _sender):
        if self._delegate.set_relay_target(str(self._target.stringValue())):
            self.refresh()

    @objc.python_method
    def _target_saved(self):
        if str(self._target.stringValue()).strip() == getattr(self, "_loaded_target", "").strip():
            return True
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("请先保存目标")
        alert.setInformativeText_("输入框中的目标尚未保存。本次不会使用旧目标发送或检查。")
        alert.runModal()
        return False

    @objc.IBAction
    def checkMessages_(self, _sender):
        if self._target_saved():
            self._delegate.check_messages()

    @objc.python_method
    def _confirm(self, title, detail):
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(detail)
        alert.addButtonWithTitle_("取消")
        alert.addButtonWithTitle_("继续")
        return alert.runModal() == AppKit.NSAlertSecondButtonReturn

    @objc.IBAction
    def sendTest_(self, _sender):
        if self._target_saved() and self._confirm(
            "发送 iMessage 测试？", "将向已保存的目标发送一条测试消息。不会通过 SIM 发送短信。"
        ):
            self._delegate.send_test_message()

    @objc.IBAction
    def retryUnknown_(self, _sender):
        if self._confirm("重发全部投递不确定项？", "请先在“信息”中核对；继续可能造成重复转发。"):
            self._delegate.retry_delivery_unknown()
            self.refresh(False)

    @objc.IBAction
    def confirmUnknown_(self, _sender):
        if self._confirm(
            "确认全部不确定项已发送？", "这些记录不会重发，对应模块短信将进入清理队列。"
        ):
            self._delegate.confirm_delivery_unknown()
            self.refresh(False)
