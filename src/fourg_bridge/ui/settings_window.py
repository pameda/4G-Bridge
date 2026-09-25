from __future__ import annotations

import AppKit
import objc


def label(text, size=13, secondary=False, weight=None):
    view = AppKit.NSTextField.wrappingLabelWithString_(text)
    view.setFont_(
        AppKit.NSFont.systemFontOfSize_weight_(
            size, AppKit.NSFontWeightRegular if weight is None else weight
        )
    )
    view.setTextColor_(
        AppKit.NSColor.secondaryLabelColor() if secondary else AppKit.NSColor.labelColor()
    )
    return view


def stack(views, horizontal=False, spacing=12):
    view = AppKit.NSStackView.stackViewWithViews_(views)
    view.setOrientation_(
        AppKit.NSUserInterfaceLayoutOrientationHorizontal
        if horizontal
        else AppKit.NSUserInterfaceLayoutOrientationVertical
    )
    view.setAlignment_(
        AppKit.NSLayoutAttributeCenterY if horizontal else AppKit.NSLayoutAttributeLeading
    )
    view.setSpacing_(spacing)
    return view


def pin(view, container, inset=20):
    container.addSubview_(view)
    view.setTranslatesAutoresizingMaskIntoConstraints_(False)
    AppKit.NSLayoutConstraint.activateConstraints_(
        [
            view.leadingAnchor().constraintEqualToAnchor_constant_(
                container.leadingAnchor(), inset
            ),
            view.trailingAnchor().constraintEqualToAnchor_constant_(
                container.trailingAnchor(), -inset
            ),
            view.topAnchor().constraintEqualToAnchor_constant_(container.topAnchor(), inset),
            view.bottomAnchor().constraintEqualToAnchor_constant_(container.bottomAnchor(), -inset),
        ]
    )


def group(views):
    box = AppKit.NSBox.alloc().init()
    box.setTitlePosition_(AppKit.NSNoTitle)
    box.setBoxType_(AppKit.NSBoxCustom)
    box.setBorderType_(AppKit.NSLineBorder)
    box.setBorderColor_(AppKit.NSColor.separatorColor())
    box.setFillColor_(AppKit.NSColor.controlBackgroundColor())
    box.setCornerRadius_(10)
    box.setContentViewMargins_(AppKit.NSMakeSize(0, 0))
    pin(stack(views), box.contentView(), 18)
    return box


def page(title, subtitle, groups):
    view = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 700, 510))
    content = stack(
        [
            label(title, 23, weight=AppKit.NSFontWeightBold),
            label(subtitle, secondary=True),
            *groups,
        ],
        spacing=18,
    )
    view.addSubview_(content)
    content.setTranslatesAutoresizingMaskIntoConstraints_(False)
    constraints = [
        content.leadingAnchor().constraintEqualToAnchor_constant_(view.leadingAnchor(), 32),
        content.trailingAnchor().constraintEqualToAnchor_constant_(view.trailingAnchor(), -32),
        content.topAnchor().constraintEqualToAnchor_constant_(view.topAnchor(), 28),
        content.bottomAnchor().constraintLessThanOrEqualToAnchor_constant_(
            view.bottomAnchor(), -24
        ),
    ]
    for item in groups:
        constraints.append(item.widthAnchor().constraintEqualToAnchor_(content.widthAnchor()))
    AppKit.NSLayoutConstraint.activateConstraints_(constraints)
    return view


class SettingsWindowController(AppKit.NSWindowController):
    def initWithDelegate_(self, delegate):
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, 700, 560),
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
        window.setTitle_("4G Bridge")
        window.setReleasedWhenClosed_(False)
        window.setBackgroundColor_(AppKit.NSColor.windowBackgroundColor())
        self._tabs = AppKit.NSTabViewController.alloc().init()
        self._tabs.setTabStyle_(AppKit.NSTabViewControllerTabStyleToolbar)
        self._tabs.setTransitionOptions_(0)
        for title, symbol, view in (
            ("连接", "antenna.radiowaves.left.and.right", self._network_page()),
            ("短信转发", "message", self._relay_page()),
            ("隐私", "hand.raised", self._privacy_page()),
            ("关于", "info.circle", self._about_page()),
        ):
            controller = AppKit.NSViewController.alloc().init()
            controller.setView_(view)
            controller.setTitle_(title)
            item = AppKit.NSTabViewItem.tabViewItemWithViewController_(controller)
            item.setLabel_(title)
            item.setImage_(
                AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, title)
            )
            self._tabs.addTabViewItem_(item)
        window.setContentViewController_(self._tabs)
        window.setToolbarStyle_(AppKit.NSWindowToolbarStylePreference)
        window.setContentSize_(AppKit.NSMakeSize(700, 540))
        window.center()
        return self

    @objc.python_method
    def _button(self, title, action):
        return AppKit.NSButton.buttonWithTitle_target_action_(title, self, action)

    @objc.python_method
    def _network_page(self):
        self._connection = label("正在检测 QDC507…", 16, weight=AppKit.NSFontWeightSemibold)
        self._network_status = label("4G 数据已关闭", secondary=True)
        self._data_button = self._button("开启 4G 数据…", "toggleData:")
        self._detail_values = {}
        rows = []
        for key, title in (
            ("operator", "运营商"),
            ("sim", "SIM 卡"),
            ("signal", "信号"),
            ("interface", "网络接口"),
            ("ipv4", "IP 地址"),
            ("gateway", "网关"),
        ):
            caption = label(title, 13, True)
            caption.widthAnchor().constraintEqualToConstant_(100).setActive_(True)
            value = label("—")
            self._detail_values[key] = value
            rows.append(stack([caption, value], True, spacing=16))
        return page(
            "连接",
            "Wi-Fi 优先，4G 随时待命。",
            [
                group(
                    [
                        self._connection,
                        self._network_status,
                        stack([self._data_button, self._button("重新检测", "rescan:")], True),
                    ]
                ),
                group([stack(rows, spacing=6)]),
                label("启动、重新检测、睡眠和退出时会关闭 4G 数据。", 12, True),
            ],
        )

    @objc.python_method
    def _relay_page(self):
        self._enabled = AppKit.NSSwitch.alloc().init()
        self._enabled.setTarget_(self)
        self._enabled.setAction_("relayChanged:")
        self._enabled.setAccessibilityLabel_("iMessage 转发")
        self._target = AppKit.NSTextField.alloc().init()
        self._target.setPlaceholderString_("手机号或 Apple ID")
        self._target.setAccessibilityLabel_("转发目标")
        self._target.widthAnchor().constraintEqualToConstant_(460).setActive_(True)
        self._target.setFont_(AppKit.NSFont.systemFontOfSize_(14))
        return page(
            "短信转发",
            "把模块收到的短信，转发到你的“信息”会话。",
            [
                group(
                    [
                        stack(
                            [
                                label("iMessage 转发", 14, weight=AppKit.NSFontWeightSemibold),
                                self._enabled,
                            ],
                            True,
                        ),
                        label("请先在 Mac 的“信息”中登录 iMessage。", 12, True),
                    ]
                ),
                group(
                    [
                        label("转发给", weight=AppKit.NSFontWeightSemibold),
                        self._target,
                        stack(
                            [
                                self._button("保存目标", "saveTarget:"),
                                self._button("发送测试消息", "sendTest:"),
                            ],
                            True,
                        ),
                    ]
                ),
                label(
                    "目标保存在 macOS 钥匙串。首次发送时，系统会请求控制“信息”的权限。", 12, True
                ),
            ],
        )

    @objc.python_method
    def _privacy_page(self):
        self._queue_info = label("转发队列正常")
        return page(
            "隐私与诊断",
            "短信留在你的设备和“信息”中。",
            [
                group(
                    [
                        label("仅保存处理状态", 14, weight=AppKit.NSFontWeightSemibold),
                        label(
                            "短信正文不写入数据库和日志；号码在诊断信息中脱敏。\n"
                            "无需辅助功能或完全磁盘访问权限。",
                            secondary=True,
                        ),
                    ]
                ),
                group(
                    [
                        self._queue_info,
                        label("若发送曾意外中断，请先在“信息”中核对，再处理不确定项。", 12, True),
                        stack(
                            [
                                self._button("重新发送不确定项", "retryUnknown:"),
                                self._button("确认已发送", "confirmUnknown:"),
                            ],
                            True,
                        ),
                    ]
                ),
            ],
        )

    @objc.python_method
    def _about_page(self):
        return page(
            "4G Bridge",
            "蜂窝连接与短信转发，为 Mac 而设计。",
            [
                group(
                    [
                        label("版本 0.1.1", 16, weight=AppKit.NSFontWeightSemibold),
                        label(
                            "支持 DJI / Baiwang QDC507 · Apple Silicon\n"
                            "原生 macOS 界面 · Wi-Fi 优先 · 本机处理",
                            secondary=True,
                        ),
                    ]
                ),
            ],
        )

    @objc.python_method
    def refresh(self, include_target=True):
        self._enabled.setState_(int(self._delegate.relay_enabled()))
        if include_target:
            self._target.setStringValue_(self._delegate.relay_target() or "")
        snapshot = self._delegate.current_snapshot()
        self._connection.setStringValue_(
            "QDC507 已连接" if snapshot.descriptor else "等待连接 QDC507"
        )
        state = snapshot.data_state.value
        status = {
            "off": "4G 数据已关闭",
            "on": "4G 数据已开启 · Wi-Fi 可用时优先使用",
            "enabling": "正在连接并检查网络…必要时会重启模块一次，请稍候。",
            "disabling": "正在关闭…",
            "protection_failed": "数据保护失败，请断开模块并重试",
        }.get(state, "正在检测…")
        self._network_status.setStringValue_(snapshot.warning or status)
        self._data_button.setTitle_("关闭 4G 数据" if state == "on" else "开启 4G 数据…")
        self._data_button.setEnabled_(
            snapshot.descriptor is not None and state not in ("enabling", "disabling")
        )
        values = {
            "operator": {"CHN-CT": "中国电信", "CHN-UNICOM": "中国联通"}.get(
                snapshot.operator, snapshot.operator or "—"
            ),
            "sim": "已就绪" if snapshot.sim_state.value == "ready" else "未就绪",
            "signal": f"{snapshot.rssi_dbm} dBm · {snapshot.rat or 'LTE'}"
            if snapshot.rssi_dbm is not None
            else "—",
            "interface": snapshot.interface or "—",
            "ipv4": snapshot.ipv4 or "未分配",
            "gateway": snapshot.gateway or "—",
        }
        for key, value in values.items():
            self._detail_values[key].setStringValue_(value)
        self._queue_info.setStringValue_(self._delegate.relay_queue_summary())

    @objc.IBAction
    def toggleData_(self, _sender):
        self._delegate.toggle_data()

    @objc.IBAction
    def rescan_(self, _sender):
        self._delegate.redetect()

    @objc.IBAction
    def relayChanged_(self, _sender):
        self._delegate.set_relay_enabled(self._enabled.state() == AppKit.NSControlStateValueOn)

    @objc.IBAction
    def saveTarget_(self, _sender):
        self._delegate.set_relay_target(str(self._target.stringValue()))

    @objc.IBAction
    def sendTest_(self, _sender):
        self._delegate.send_test_message()

    @objc.IBAction
    def retryUnknown_(self, _sender):
        self._delegate.retry_delivery_unknown()
        self.refresh(False)

    @objc.IBAction
    def confirmUnknown_(self, _sender):
        self._delegate.confirm_delivery_unknown()
        self.refresh(False)
