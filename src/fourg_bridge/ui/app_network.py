"""Native process list shared by the full page and compact menu panel."""

import AppKit
import objc

from fourg_bridge.support.presentation import format_bytes


class AppNetworkTable(AppKit.NSObject):
    def initWithCompact_(self, compact):
        self = objc.super(AppNetworkTable, self).init()
        if self is None:
            return None
        self.rows = ()
        self.compact = compact
        self.table = AppKit.NSTableView.alloc().init()
        columns = [
            ("app", "应用 / 进程", 140 if compact else 240),
            ("down", "下载", 82 if compact else 90),
            ("up", "上传", 82 if compact else 90),
        ]
        if not compact:
            columns += [("total", "本次观测", 120)]
        for key, title, width in columns:
            column = AppKit.NSTableColumn.alloc().initWithIdentifier_(key)
            column.setTitle_(title)
            column.setWidth_(width)
            self.table.addTableColumn_(column)
        self.table.setRowHeight_(30 if compact else 38)
        self.table.setStyle_(AppKit.NSTableViewStyleInset)
        self.table.setUsesAlternatingRowBackgroundColors_(not compact)
        self.table.setDataSource_(self)
        self.table.setDelegate_(self)
        self.table.setAccessibilityLabel_("应用网络实时计数")
        self.view = AppKit.NSScrollView.alloc().init()
        self.view.setDocumentView_(self.table)
        self.view.setHasVerticalScroller_(not compact)
        self.view.setAutohidesScrollers_(True)
        self.view.heightAnchor().constraintEqualToConstant_(110 if compact else 320).setActive_(
            True
        )
        return self

    @objc.python_method
    def update(self, rows):
        self.rows = rows[:3] if self.compact else rows
        self.table.reloadData()

    def numberOfRowsInTableView_(self, _table):
        return len(self.rows)

    def tableView_viewForTableColumn_row_(self, _table, column, index):
        row = self.rows[index]
        key = column.identifier()
        if key == "app":
            app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(row.pid)
            name = (app.localizedName() if app else None) or row.name
            cell = AppKit.NSTableCellView.alloc().initWithFrame_(((0, 0), (column.width(), 36)))
            icon = AppKit.NSImageView.alloc().initWithFrame_(((5, 8), (20, 20)))
            icon.setImage_(
                app.icon()
                if app
                else AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "app.dashed", None
                )
            )
            icon.setImageScaling_(AppKit.NSImageScaleProportionallyDown)
            text = AppKit.NSTextField.labelWithString_(name)
            text.setFrame_(((32, 9), (column.width() - 38, 20)))
            text.setFont_(AppKit.NSFont.systemFontOfSize_(12))
            text.setToolTip_(f"{name} · PID {row.pid} · 系统汇总，不推断物理出口")
            cell.addSubview_(icon)
            cell.addSubview_(text)
            cell.setImageView_(icon)
            cell.setTextField_(text)
            return cell
        value = {
            "down": format_bytes(row.download) + "/s",
            "up": format_bytes(row.upload) + "/s",
            "total": format_bytes(row.observed_bytes),
        }[key]
        text = AppKit.NSTextField.labelWithString_(value)
        text.setFont_(
            AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(11, AppKit.NSFontWeightRegular)
        )
        text.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        return text
