from __future__ import annotations

import AppKit
import objc


class SettingsWindowController(AppKit.NSWindowController):
    def initWithDelegate_(self, delegate: object):
        rect = AppKit.NSMakeRect(0, 0, 560, 390)
        style = (
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskMiniaturizable
        )
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False
        )
        self = objc.super(SettingsWindowController, self).initWithWindow_(window)
        if self is None:
            return None
        self._delegate = delegate
        window.setTitle_("4G Bridge 设置")
        window.setReleasedWhenClosed_(False)
        window.center()
        self._build()
        return self

    def _build(self) -> None:
        tab_view = AppKit.NSTabView.alloc().initWithFrame_(AppKit.NSMakeRect(18, 18, 524, 354))
        self.window().contentView().addSubview_(tab_view)
        tab_view.addTabViewItem_(self._relay_tab())
        tab_view.addTabViewItem_(
            self._info_tab(
                "模块与网络",
                "网络与模块状态仅做只读探测。\n4G 数据每次启动、重连、睡眠与唤醒后都保持关闭。",
            )
        )
        tab_view.addTabViewItem_(
            self._info_tab(
                "隐私与诊断",
                "短信正文不写入数据库或普通日志。\n日志中的号码、ICCID 与 Apple ID 会自动脱敏。",
            )
        )
        tab_view.addTabViewItem_(
            self._info_tab(
                "关于", "4G Bridge 0.1.0\nQDC507 Modem Controller + SMS to iMessage Bridge"
            )
        )

    def _relay_tab(self):
        item = AppKit.NSTabViewItem.alloc().initWithIdentifier_("relay")
        item.setLabel_("iMessage 转发")
        view = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 500, 320))
        self._enabled = AppKit.NSButton.checkboxWithTitle_target_action_(
            "启用 iMessage 转发", self, "relayChanged:"
        )
        self._enabled.setFrame_(AppKit.NSMakeRect(22, 255, 300, 28))
        view.addSubview_(self._enabled)
        label = AppKit.NSTextField.labelWithString_("转发目标（手机号或 Apple ID）")
        label.setFrame_(AppKit.NSMakeRect(22, 215, 320, 22))
        view.addSubview_(label)
        self._target = AppKit.NSSecureTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(22, 176, 450, 30)
        )
        self._target.setPlaceholderString_("手机号或 Apple ID")
        view.addSubview_(self._target)
        save = AppKit.NSButton.buttonWithTitle_target_action_("保存", self, "saveTarget:")
        save.setBezelStyle_(AppKit.NSBezelStyleRounded)
        save.setFrame_(AppKit.NSMakeRect(330, 124, 68, 32))
        view.addSubview_(save)
        test = AppKit.NSButton.buttonWithTitle_target_action_("发送测试消息", self, "sendTest:")
        test.setBezelStyle_(AppKit.NSBezelStyleRounded)
        test.setFrame_(AppKit.NSMakeRect(404, 124, 108, 32))
        view.addSubview_(test)
        note = AppKit.NSTextField.wrappingLabelWithString_(
            "首次发送时，macOS 会请求允许 4G Bridge 控制“信息”。"
            "AppleScript 接受请求不等同于对端送达。"
        )
        note.setFrame_(AppKit.NSMakeRect(22, 62, 460, 48))
        note.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        view.addSubview_(note)
        item.setView_(view)
        return item

    @staticmethod
    def _info_tab(title: str, text: str):
        item = AppKit.NSTabViewItem.alloc().initWithIdentifier_(title)
        item.setLabel_(title)
        view = AppKit.NSVisualEffectView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 500, 320))
        view.setMaterial_(AppKit.NSVisualEffectMaterialContentBackground)
        label = AppKit.NSTextField.wrappingLabelWithString_(text)
        label.setFrame_(AppKit.NSMakeRect(28, 190, 440, 90))
        view.addSubview_(label)
        item.setView_(view)
        return item

    @objc.python_method
    def refresh(self) -> None:
        self._enabled.setState_(
            AppKit.NSControlStateValueOn
            if self._delegate.relay_enabled()
            else AppKit.NSControlStateValueOff
        )
        self._target.setStringValue_(self._delegate.relay_target() or "")

    @objc.IBAction
    def relayChanged_(self, _sender):
        self._delegate.set_relay_enabled(self._enabled.state() == AppKit.NSControlStateValueOn)

    @objc.IBAction
    def saveTarget_(self, _sender):
        self._delegate.set_relay_target(str(self._target.stringValue()))

    @objc.IBAction
    def sendTest_(self, _sender):
        self._delegate.send_test_message()
