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
from fourg_bridge.ui.app_network import AppNetworkTable
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
            ("应用网络", "network", self._app_network_page()),
            ("运营商", "simcard", self._carrier_page()),
            ("运行日志", "list.bullet.rectangle", self._log_page()),
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
        self._authorize_button = self._button("授权读取目标", "authorizeTarget:")
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
                                        label(
                                            "通过 Mac 当前网络发送，Wi-Fi 下无需开启 4G 数据。",
                                            12,
                                            True,
                                        ),
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
                                self._authorize_button,
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
                            "启动／拔插／唤醒先关闭数据；授权自动接管后会重新检测 Wi-Fi。",
                            12,
                            True,
                        ),
                        self._button("重新检测模块", "rescan:"),
                    ]
                ),
            ],
        )

    @objc.python_method
    def _log_page(self):
        self._log_filter = AppKit.NSPopUpButton.alloc().init()
        self._log_filter.addItemsWithTitles_(["全部事件", "仅警告"])
        self._log_filter.setTarget_(self)
        self._log_filter.setAction_("logFilterChanged:")
        self._log_text = AppKit.NSTextView.alloc().initWithFrame_(((0, 0), (700, 360)))
        self._log_text.setEditable_(False)
        self._log_text.setSelectable_(True)
        self._log_text.setFont_(
            AppKit.NSFont.monospacedSystemFontOfSize_weight_(12, AppKit.NSFontWeightRegular)
        )
        self._log_text.setTextColor_(AppKit.NSColor.labelColor())
        self._log_text.setBackgroundColor_(AppKit.NSColor.textBackgroundColor())
        self._log_text.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        self._log_text.textContainer().setWidthTracksTextView_(True)
        scroll = AppKit.NSScrollView.alloc().init()
        scroll.setDocumentView_(self._log_text)
        scroll.setHasVerticalScroller_(True)
        scroll.heightAnchor().constraintEqualToConstant_(360).setActive_(True)
        return page(
            "运行日志",
            "连接变化与运行状态，清楚可查。",
            [
                group(
                    [
                        stack(
                            [
                                self._log_filter,
                                self._button("复制日志", "copyLogs:"),
                                self._button("清空", "clearLogs:"),
                            ],
                            True,
                        ),
                        scroll,
                        label(
                            "仅保留本次运行最近 500 条事件，退出即清除。\n"
                            "不记录短信正文、号码、Apple ID 或访问地址。",
                            11,
                            True,
                        ),
                    ]
                )
            ],
        )

    @objc.python_method
    def refresh_logs(self):
        text = self._delegate.event_log(self._log_filter.indexOfSelectedItem() == 1)
        text = text or "暂无运行事件"
        if self._log_text.string() != text:
            self._log_text.setString_(text)

    @objc.IBAction
    def logFilterChanged_(self, _sender):
        self.refresh_logs()

    @objc.IBAction
    def copyLogs_(self, _sender):
        board = AppKit.NSPasteboard.generalPasteboard()
        board.clearContents()
        board.setString_forType_(self._log_text.string(), AppKit.NSPasteboardTypeString)

    @objc.IBAction
    def clearLogs_(self, _sender):
        self._delegate.clear_event_log()
        self.refresh_logs()

    @objc.python_method
    def _app_network_page(self):
        self._app_table = AppNetworkTable.alloc().initWithCompact_(False)
        self._app_network_status = label("等待系统计数", 12, True)
        self._app_pause = self._button("暂停观测", "toggleAppNetwork:")
        return page(
            "应用网络",
            "查看哪些应用正在使用网络。",
            [
                group(
                    [
                        stack([section_title("APP NETWORK", "network"), self._app_pause], True),
                        self._app_network_status,
                        self._app_table.view,
                        label(
                            "按实时速率排序。仅在此页或菜单面板打开时采样，本次观测累计只保存在内存。\n"
                            "所有接口的进程计数（含本地回环），不是 SIM 账单；"
                            "VPN／代理可能重复计数，不能据此判断 Wi-Fi／4G 出口。",
                            11,
                            True,
                        ),
                    ]
                )
            ],
        )

    @objc.python_method
    def _carrier_page(self):
        self._carrier_number = AppKit.NSPopUpButton.alloc().init()
        self._carrier_number.addItemsWithTitles_(["10001", "10086", "10010"])
        self._carrier_number.setAccessibilityLabel_("运营商短信服务号")
        self._carrier_command = AppKit.NSTextField.textFieldWithString_("108")
        self._carrier_command.widthAnchor().constraintEqualToConstant_(100).setActive_(True)
        self._carrier_command.setAccessibilityLabel_("运营商查询指令")
        self._carrier_button = self._button("查询一次…", "queryCarrier:")
        self._carrier_note = label("尚未发送查询", 12, True)
        self._carrier_remaining = label("—", 30, weight=AppKit.NSFontWeightSemibold, numeric=True)
        self._carrier_updated = label("等待运营商短信回复", 12, True)
        self._carrier_policy = label("尚未启用套餐保护", 12, True)
        return page(
            "运营商流量",
            "套餐余量与本机计数，分开查看。",
            [
                group(
                    [
                        section_title("剩余流量 · 短信识别", "simcard"),
                        self._carrier_remaining,
                        self._carrier_updated,
                        self._carrier_policy,
                        self._button("启用／停用套餐自动接管…", "carrierPolicy:"),
                        label(
                            "电信通用流量包含明确列出的结转项；不累加通话、促销或重叠套餐。",
                            11,
                            True,
                        ),
                    ]
                ),
                group(
                    [
                        section_title("手动查询", "paperplane"),
                        stack(
                            [
                                label("服务号", 12),
                                self._carrier_number,
                                label("指令", 12),
                                self._carrier_command,
                                self._carrier_button,
                            ],
                            True,
                        ),
                        self._carrier_note,
                        label(
                            "预填电信 10001 / 108。地区、运营商及套餐可能不同，发送前请核实。\n"
                            "查询短信可能收费，发送前再次确认；自动定时查询关闭。\n"
                            "收到的原文仍按你的 iMessage 开关转发；未转发成功不删除。",
                            11,
                            True,
                        ),
                    ]
                ),
            ],
        )

    @objc.python_method
    def _preferences_page(self):
        self._login = AppKit.NSSwitch.alloc().init()
        self._login.setAccessibilityLabel_("登录时启动 4G Bridge")
        self._login.setTarget_(self)
        self._login.setAction_("loginChanged:")
        self._login_status = label("读取系统登录项状态", 11, True)
        self._auto_enabled = AppKit.NSSwitch.alloc().init()
        self._auto_enabled.setAccessibilityLabel_("Wi-Fi 故障自动接管")
        self._data_limit = AppKit.NSTextField.alloc().init()
        self._data_limit.setPlaceholderString_("输入上限")
        self._data_limit.setAccessibilityLabel_("4G 流量上限 GB")
        self._data_limit.widthAnchor().constraintEqualToConstant_(110).setActive_(True)
        self._budget_period = AppKit.NSPopUpButton.alloc().init()
        self._budget_period.addItemsWithTitles_(["每份额度", "每自然月"])
        self._policy_status = label("自动接管未开启", 12, True)
        self._budget_usage = label("尚未设置流量上限", 12, True)
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
                        stack(
                            [
                                section_title("Wi-Fi 故障自动接管", "wifi.exclamationmark"),
                                self._auto_enabled,
                            ],
                            True,
                        ),
                        stack(
                            [
                                label("4G 上限", 12),
                                self._data_limit,
                                label("GB", 12, True),
                                self._budget_period,
                                self._button("保存策略…", "saveDataPolicy:"),
                            ],
                            True,
                        ),
                        self._budget_usage,
                        self._policy_status,
                        label(
                            "Wi-Fi 明确断开时快速接管，互联网故障需连续确认；VPN 配置不变。\n"
                            "到顶锁定，重启或跨月不会解锁。手动追加相同额度后才能继续。\n"
                            "本机计量，非运营商账单；采样和断开存在延迟，可能超额。",
                            11,
                            True,
                        ),
                        self._button("手动追加一份额度…", "grantData:"),
                    ]
                ),
                group(
                    [
                        section_title("外观", "circle.lefthalf.filled"),
                        self._appearance,
                        stack([label("登录时启动", 12), self._login, self._login_status], True),
                    ]
                ),
                group(
                    [
                        section_title("隐私保护", "hand.raised"),
                        label(
                            "短信正文不写入数据库或普通日志，诊断号码自动脱敏。\n"
                            "不访问 Messages 数据库，不抓包，不申请完全磁盘访问。",
                            11,
                            True,
                        ),
                        label(f"4G Bridge {__version__} · Apple Silicon · QDC507", 11, True),
                    ]
                ),
            ],
        )

    @objc.python_method
    def refresh(self, include_target=True):
        self.refresh_logs()
        self._carrier_policy.setStringValue_(self._delegate.carrier_policy_status())
        login_state, login_text = self._delegate.login_status()
        self._login.setState_(int(login_state == 1))
        self._login_status.setStringValue_(login_text)
        carrier_busy, carrier_status, allowance = self._delegate.carrier_state()
        self._carrier_button.setEnabled_(not carrier_busy)
        self._carrier_note.setStringValue_(carrier_status)
        self._carrier_remaining.setStringValue_(
            f"{allowance.amount} {allowance.unit}" if allowance else "—"
        )
        self._carrier_updated.setStringValue_(
            f"{allowance.timestamp:%m-%d %H:%M} · {allowance.sender} · 仅本次运行缓存"
            if allowance
            else "等待明确的剩余流量回复；未识别时请在“信息”查看原文。"
        )
        self.refresh_app_network()
        diagnostic = getattr(self._delegate, "diagnostic_mode", False)
        self.window().setTitle_("4G Bridge · 短信测试模式" if diagnostic else "4G Bridge")
        settings, used, policy_status = self._delegate.data_policy()
        self._data_limit.setEnabled_(not settings.carrier_policy_enabled)
        self._budget_period.setEnabled_(not settings.carrier_policy_enabled)
        if include_target:
            self._auto_enabled.setState_(int(settings.auto_data_enabled))
            self._data_limit.setStringValue_(
                f"{settings.data_limit_bytes / 1_000_000_000:g}"
                if settings.data_limit_bytes
                else ""
            )
            self._budget_period.selectItemAtIndex_(int(settings.data_budget_period == "month"))
        self._policy_status.setStringValue_(policy_status)
        self._budget_usage.setStringValue_(
            f"当前额度已用 {format_bytes(used)} / {format_bytes(settings.data_limit_bytes)}"
        )
        self._enabled.setState_(int(self._delegate.relay_enabled()))
        self._enabled.setEnabled_(not getattr(self._delegate, "diagnostic_mode", False))
        if include_target:
            self._loaded_target = self._delegate.relay_target() or ""
            self._target.setStringValue_(self._loaded_target)
        busy, bridge_status = self._delegate.bridge_status()
        self._bridge_status.setStringValue_(bridge_status)
        if getattr(self._delegate, "diagnostic_mode", False):
            self._bridge_status.setStringValue_(
                "测试模式：不读取模块短信、不自动转发、不控制 4G。\n" + bridge_status
            )
        self._check_button.setEnabled_(not busy)
        self._test_button.setEnabled_(not busy)
        self._authorize_button.setEnabled_(not busy)
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
        self._rescan.setTitle_("恢复模块控制…" if diagnostic else "重新检测")
        if diagnostic:
            self._connection.setStringValue_("模块检测已暂停")
            self._connection_detail.setStringValue_("当前为短信测试模式，不代表 USB 模块未连接。")
            self._network_status.setStringValue_(
                "点击“恢复模块控制”退出测试；短信转发将遵循已保存的开关。"
            )
            self._data_button.setEnabled_(False)
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
        if diagnostic:
            self._device_status.setStringValue_("短信测试模式 · 模块检测已暂停")
            self._device_warning.setStringValue_(
                "并非模块未插入，无需反复拔插。点击下方“重新检测模块”可恢复控制。"
            )
            for value in self._details.values():
                value.setStringValue_("测试模式未检测")
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
    def refresh_app_network(self):
        rows, status, paused = self._delegate.app_network_state()
        self._app_table.update(rows)
        self._app_network_status.setStringValue_(status)
        self._app_pause.setTitle_("继续观测" if paused else "暂停观测")

    @objc.IBAction
    def toggleAppNetwork_(self, _sender):
        self._delegate.toggle_app_network()

    @objc.IBAction
    def carrierPolicy_(self, _sender):
        self._delegate.toggle_carrier_policy()
        self.refresh(False)

    @objc.IBAction
    def queryCarrier_(self, _sender):
        self._delegate.query_carrier(
            self._carrier_number.titleOfSelectedItem(), self._carrier_command.stringValue().strip()
        )

    @objc.IBAction
    def loginChanged_(self, _sender):
        self._delegate.set_login_enabled(bool(self._login.state()))

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
    def saveDataPolicy_(self, _sender):
        if self._delegate.data_policy()[0].carrier_policy_enabled:
            self._delegate._show_alert(
                "正在使用运营商套餐保护", "请到运营商页管理 80% / 98% 保护与自动接管。"
            )
            return
        enabled = bool(self._auto_enabled.state())
        if enabled and not self._confirm(
            "允许 Wi-Fi 故障时自动使用 SIM 流量？",
            "以约 2 秒间隔检查 Wi-Fi；明确断开直接请求接管，联网探测自身有超时等待。"
            "连续失败后临时提高 QDC507 优先级，恢复后还原。"
            "网卡无法恢复时，最多重启模块一次，可能短暂中断短信接收；失败即暂停。"
            "仅在应用运行时保护流量；不会更改 VPN、DNS 或 Wi-Fi 开关。",
        ):
            return
        if self._delegate.save_data_policy(
            enabled,
            str(self._data_limit.stringValue()),
            self._budget_period.indexOfSelectedItem() == 1,
        ):
            self.refresh()

    @objc.IBAction
    def grantData_(self, _sender):
        if self._confirm(
            "追加一份 4G 额度？",
            "将解除限额锁定，并按已保存的上限追加同等额度，不会清除今日／本月流量。"
            "自动接管开启时，断网后可再次使用 SIM 流量。",
        ):
            self._delegate.grant_data_allowance()

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

    @objc.IBAction
    def authorizeTarget_(self, _sender):
        self._delegate.authorize_relay_target()

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
