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
        module_tab, self._module_info = self._info_tab(
            "模块与网络",
            "网络与模块状态仅做只读探测。\nWi‑Fi 与 4G 同时连接时，默认流量始终优先走 Wi‑Fi。",
        )
        tab_view.addTabViewItem_(module_tab)
        tab_view.addTabViewItem_(self._diagnostics_tab())
        about_tab, _ = self._info_tab(
            "关于", "4G Bridge 0.1.0\nQDC507 Modem Controller + SMS to iMessage Bridge"
        )
        tab_view.addTabViewItem_(about_tab)

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

    def _diagnostics_tab(self):
        item = AppKit.NSTabViewItem.alloc().initWithIdentifier_("diagnostics")
        item.setLabel_("隐私与诊断")
        view = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 500, 320))
        privacy = AppKit.NSTextField.wrappingLabelWithString_(
            "短信正文不写入数据库或普通日志。日志中的号码、ICCID 与 Apple ID 会自动脱敏。"
        )
        privacy.setFrame_(AppKit.NSMakeRect(22, 238, 456, 44))
        privacy.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        view.addSubview_(privacy)
        self._queue_info = AppKit.NSTextField.wrappingLabelWithString_("转发队列：正常")
        self._queue_info.setFrame_(AppKit.NSMakeRect(22, 156, 456, 64))
        view.addSubview_(self._queue_info)
        retry = AppKit.NSButton.buttonWithTitle_target_action_(
            "重新发送不确定项", self, "retryUnknown:"
        )
        retry.setBezelStyle_(AppKit.NSBezelStyleRounded)
        retry.setFrame_(AppKit.NSMakeRect(208, 104, 138, 32))
        view.addSubview_(retry)
        confirm = AppKit.NSButton.buttonWithTitle_target_action_(
            "确认已接受并清理", self, "confirmUnknown:"
        )
        confirm.setBezelStyle_(AppKit.NSBezelStyleRounded)
        confirm.setFrame_(AppKit.NSMakeRect(352, 104, 138, 32))
        view.addSubview_(confirm)
        note = AppKit.NSTextField.wrappingLabelWithString_(
            "仅当上次发送在数据库确认前中断时使用；应用默认不会自动重发，以避免重复。"
        )
        note.setFrame_(AppKit.NSMakeRect(22, 50, 456, 42))
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
        label.setFrame_(AppKit.NSMakeRect(28, 72, 440, 210))
        view.addSubview_(label)
        item.setView_(view)
        return item, label

    @objc.python_method
    def refresh(self) -> None:
        self._enabled.setState_(
            AppKit.NSControlStateValueOn
            if self._delegate.relay_enabled()
            else AppKit.NSControlStateValueOff
        )
        self._target.setStringValue_(self._delegate.relay_target() or "")
        self._module_info.setStringValue_(self._delegate.modem_details())
        self._queue_info.setStringValue_(self._delegate.relay_queue_summary())

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
        self.refresh()

    @objc.IBAction
    def confirmUnknown_(self, _sender):
        self._delegate.confirm_delivery_unknown()
        self.refresh()
