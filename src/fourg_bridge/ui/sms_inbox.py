"""Native received-message list and selectable, plain-text detail view."""

import AppKit
import Foundation
import objc

from fourg_bridge.ui.components import label, section_title, stack


class WrappedSMSScrollView(AppKit.NSScrollView):
    def tile(self):
        objc.super(WrappedSMSScrollView, self).tile()
        text = self.documentView()
        if text is None or getattr(self, "_sizing_text", False):
            return
        self._sizing_text = True
        try:
            size = self.contentSize()
            width = max(1, size.width)
            text.setFrameSize_(AppKit.NSMakeSize(width, max(size.height, text.frame().size.height)))
            text.textContainer().setContainerSize_(
                AppKit.NSMakeSize(max(1, width - 2 * text.textContainerInset().width), 1e7)
            )
            text.layoutManager().ensureLayoutForTextContainer_(text.textContainer())
            used = text.layoutManager().usedRectForTextContainer_(text.textContainer())
            text.setFrameSize_(
                AppKit.NSMakeSize(
                    width, max(size.height, used.size.height + 2 * text.textContainerInset().height)
                )
            )
        finally:
            self._sizing_text = False


class SMSInboxTable(AppKit.NSTableView):
    def hitTest_(self, point):
        hit = objc.super(SMSInboxTable, self).hitTest_(point)
        return self if hit is not None else None

    def acceptsFirstMouse_(self, _event):
        return True


class SMSInboxView(AppKit.NSObject):
    def init(self):
        self = objc.super(SMSInboxView, self).init()
        if self is None:
            return None
        self._all_rows = ()
        self.rows = ()
        self._selected_key = None
        self._detail_value = None
        self.search = AppKit.NSSearchField.alloc().init()
        self.search.setPlaceholderString_("搜索发件人或短信内容")
        self.search.setAccessibilityLabel_("搜索收到的短信")
        self.search.setDelegate_(self)
        self.summary = label("暂无短信，收到后会自动显示。", 12, True)
        self.table = SMSInboxTable.alloc().init()
        for key, title, width in (
            ("sender", "发件人", 120),
            ("time", "接收时间", 145),
            ("body", "内容摘要", 235),
            ("status", "转发状态", 150),
        ):
            column = AppKit.NSTableColumn.alloc().initWithIdentifier_(key)
            column.setTitle_(title)
            column.setWidth_(width)
            self.table.addTableColumn_(column)
        self.table.setRowHeight_(34)
        self.table.setColumnAutoresizingStyle_(AppKit.NSTableViewUniformColumnAutoresizingStyle)
        self.table.setStyle_(AppKit.NSTableViewStyleInset)
        self.table.setUsesAlternatingRowBackgroundColors_(True)
        self.table.setAllowsMultipleSelection_(False)
        self.table.setDataSource_(self)
        self.table.setDelegate_(self)
        self.table.setAccessibilityLabel_("收到的短信列表")
        listing = AppKit.NSScrollView.alloc().init()
        listing.setDocumentView_(self.table)
        listing.setHasVerticalScroller_(True)
        listing.setHasHorizontalScroller_(True)
        listing.setAutohidesScrollers_(True)
        listing.heightAnchor().constraintEqualToConstant_(180).setActive_(True)
        self.detail_title = label("选择短信查看完整内容", 13, weight=AppKit.NSFontWeightMedium)
        self.detail = AppKit.NSTextView.alloc().initWithFrame_(((0, 0), (650, 160)))
        self.detail.setEditable_(False)
        self.detail.setSelectable_(True)
        self.detail.setRichText_(False)
        self.detail.setAutomaticLinkDetectionEnabled_(False)
        self.detail.setUsesFindBar_(False)
        self.detail.setFont_(AppKit.NSFont.systemFontOfSize_(13))
        self.detail.setTextColor_(AppKit.NSColor.labelColor())
        self.detail.setBackgroundColor_(AppKit.NSColor.textBackgroundColor())
        self.detail.setTextContainerInset_(AppKit.NSMakeSize(10, 10))
        self.detail.setMinSize_(AppKit.NSMakeSize(0, 240))
        self.detail.setMaxSize_(AppKit.NSMakeSize(1e7, 1e7))
        self.detail.setVerticallyResizable_(True)
        self.detail.setHorizontallyResizable_(False)
        self.detail.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        self.detail.textContainer().setWidthTracksTextView_(True)
        self.detail.textContainer().setHeightTracksTextView_(False)
        paragraph = AppKit.NSMutableParagraphStyle.alloc().init()
        paragraph.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        paragraph.setParagraphSpacing_(6)
        self.detail.setDefaultParagraphStyle_(paragraph)
        self.detail.setAccessibilityLabel_("短信完整正文，可选择并复制")
        body = WrappedSMSScrollView.alloc().init()
        body.setDocumentView_(self.detail)
        body.setHasVerticalScroller_(True)
        body.setHasHorizontalScroller_(False)
        body.setAutohidesScrollers_(True)
        body.heightAnchor().constraintEqualToConstant_(240).setActive_(True)
        self.view = stack(
            [
                section_title("收到的短信", "tray.full"),
                self.search,
                self.summary,
                listing,
                self.detail_title,
                label("完整正文 · 自动换行，可上下滚动、选择复制", 11, True),
                body,
                label(
                    "仅本次运行保留最近 200 条；退出或更换 SIM 后清空，不写入磁盘。\n"
                    "已从模块删除的旧短信无法恢复。Messages 已接受不代表对方已收到。",
                    11,
                    True,
                ),
            ],
            spacing=10,
        )
        for view in (self.search, listing, body, self.detail_title, self.summary):
            view.widthAnchor().constraintEqualToAnchor_(self.view.widthAnchor()).setActive_(True)
        return self

    @objc.python_method
    def update(self, rows):
        if rows == self._all_rows:
            return
        self._all_rows = rows
        self._reload()

    @objc.python_method
    def _reload(self):
        query = str(self.search.stringValue()).strip().casefold()
        self.rows = tuple(
            row
            for row in self._all_rows
            if not query or query in row.sender.casefold() or query in row.body.casefold()
        )
        selected = self._selected_key
        self.table.reloadData()
        index = next(
            (i for i, row in enumerate(self.rows) if row.message_hash == selected),
            0 if self.rows else -1,
        )
        if index >= 0:
            self.table.selectRowIndexes_byExtendingSelection_(
                Foundation.NSIndexSet.indexSetWithIndex_(index), False
            )
        else:
            self.table.deselectAll_(None)
        self.summary.setStringValue_(
            f"{len(self.rows)} 条匹配 · 本次接收 {len(self._all_rows)} 条"
            if query
            else f"本次接收 {len(self.rows)} 条 · 最新在前"
            if self.rows
            else "暂无短信，收到后会自动显示；转发关闭时仍可查看。"
        )
        self._show_selection()

    @objc.python_method
    def _show_selection(self):
        index = self.table.selectedRow()
        row = self.rows[index] if 0 <= index < len(self.rows) else None
        self._selected_key = row.message_hash if row else None
        self.detail_title.setStringValue_(
            f"{row.sender} · {row.timestamp.astimezone():%Y-%m-%d %H:%M:%S} · {row.status_label}"
            if row
            else "选择短信查看完整内容"
        )
        value = (row.message_hash, row.body) if row else None
        if value != self._detail_value:
            self.detail.setString_(row.body if row else "")
            # Reset the clip origin, not the caret, to preserve the leading inset.
            scroll = self.detail.enclosingScrollView()
            scroll.tile()
            scroll.contentView().scrollToPoint_(AppKit.NSMakePoint(0, 0))
            scroll.reflectScrolledClipView_(scroll.contentView())
            self._detail_value = value

    def controlTextDidChange_(self, _notification):
        self._reload()

    def numberOfRowsInTableView_(self, _table):
        return len(self.rows)

    def tableViewSelectionDidChange_(self, _notification):
        self._show_selection()

    def tableView_viewForTableColumn_row_(self, _table, column, index):
        row = self.rows[index]
        value = {
            "sender": row.sender,
            "time": row.timestamp.astimezone().strftime("%m-%d %H:%M:%S"),
            "body": " ".join(row.body.split()),
            "status": row.status_label,
        }[column.identifier()]
        text = AppKit.NSTextField.labelWithString_(value)
        text.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        text.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        return text
