"""Native source-list navigation; stable page indices preserve controller contracts."""

import AppKit
import Foundation
import objc

from fourg_bridge.ui.components import label, pin, stack, symbol

DESTINATIONS = (
    (0, "连接总览", "square.grid.2x2"),
    (1, "本机流量", "chart.xyaxis.line"),
    (6, "运营商套餐", "simcard"),
    (2, "短信转发", "message"),
    (5, "应用网络", "network"),
    (3, "设备与网络", "antenna.radiowaves.left.and.right"),
    (7, "运行日志", "list.bullet.rectangle"),
    (4, "设置", "gearshape"),
)


class SidebarTable(AppKit.NSTableView):
    def hitTest_(self, point):
        # This source list contains display-only cells. Let NSTableView handle
        # the entire row instead of labels/images intercepting mouseDown.
        hit = objc.super(SidebarTable, self).hitTest_(point)
        return self if hit is not None else None

    def acceptsFirstMouse_(self, _event):
        return True


class SidebarCell(AppKit.NSTableCellView):
    def setBackgroundStyle_(self, _style):
        objc.super(SidebarCell, self).setBackgroundStyle_(AppKit.NSBackgroundStyleNormal)


class NavigationTabs(AppKit.NSTabViewController):
    def setSelectedTabViewItemIndex_(self, index):
        objc.super(NavigationTabs, self).setSelectedTabViewItemIndex_(index)
        sidebar = getattr(self, "sidebar", None)
        if sidebar is not None:
            sidebar.select(index)


class Sidebar(AppKit.NSObject):
    def initWithTabs_(self, tabs):
        self = objc.super(Sidebar, self).init()
        if self is None:
            return None
        self.tabs = tabs
        self.view = AppKit.NSVisualEffectView.alloc().init()
        self.view.setMaterial_(AppKit.NSVisualEffectMaterialSidebar)
        self.view.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        self.view.setState_(AppKit.NSVisualEffectStateFollowsWindowActiveState)
        title = stack(
            [
                symbol("antenna.radiowaves.left.and.right", 24),
                stack(
                    [
                        label("4G Bridge", 16, weight=AppKit.NSFontWeightSemibold),
                        label("你的蜂窝连接中心", 10, True),
                    ],
                    spacing=3,
                ),
            ],
            True,
            10,
        )
        self.table = SidebarTable.alloc().init()
        column = AppKit.NSTableColumn.alloc().initWithIdentifier_("destination")
        column.setWidth_(170)
        self.table.addTableColumn_(column)
        self.table.setHeaderView_(None)
        self.table.setStyle_(AppKit.NSTableViewStyleSourceList)
        self.table.setSelectionHighlightStyle_(AppKit.NSTableViewSelectionHighlightStyleRegular)
        self.table.setRowHeight_(38)
        self.table.setAllowsEmptySelection_(False)
        self.table.setAllowsMultipleSelection_(False)
        self.table.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.table.setDataSource_(self)
        self.table.setDelegate_(self)
        self.table.setAccessibilityLabel_("功能导航")
        scroll = AppKit.NSScrollView.alloc().init()
        scroll.setDrawsBackground_(False)
        scroll.setDocumentView_(self.table)
        scroll.setHasVerticalScroller_(False)
        scroll.heightAnchor().constraintEqualToConstant_(340).setActive_(True)
        self.status = label("QDC507 · 等待连接", 11, True)
        self.status.setAccessibilityLabel_("模块连接状态")
        self.footnote = label("本机处理 · 隐私优先", 10, True)
        content = stack([title, scroll, self.status, self.footnote], spacing=20)
        self.view.addSubview_(content)
        content.setTranslatesAutoresizingMaskIntoConstraints_(False)
        AppKit.NSLayoutConstraint.activateConstraints_(
            [
                content.topAnchor().constraintEqualToAnchor_constant_(self.view.topAnchor(), 28),
                content.leadingAnchor().constraintEqualToAnchor_constant_(
                    self.view.leadingAnchor(), 14
                ),
                content.trailingAnchor().constraintEqualToAnchor_constant_(
                    self.view.trailingAnchor(), -14
                ),
                scroll.widthAnchor().constraintEqualToAnchor_(content.widthAnchor()),
            ]
        )
        self.table.reloadData()
        self.select(0)
        return self

    @objc.python_method
    def select(self, index):
        row = next(i for i, entry in enumerate(DESTINATIONS) if entry[0] == index)
        if self.table.selectedRow() != row:
            self.table.selectRowIndexes_byExtendingSelection_(
                Foundation.NSIndexSet.indexSetWithIndex_(row), False
            )

    def numberOfRowsInTableView_(self, _table):
        return len(DESTINATIONS)

    def tableView_viewForTableColumn_row_(self, _table, _column, row):
        _index, title, icon = DESTINATIONS[row]
        cell = SidebarCell.alloc().init()
        image = symbol(icon, 18)
        text = label(title, 13)
        text.setSelectable_(False)
        text.setEditable_(False)
        pin(stack([image, text], True, 10), cell, 6)
        cell.setTextField_(text)
        cell.setImageView_(image)
        return cell

    def tableViewSelectionDidChange_(self, _notification):
        row = self.table.selectedRow()
        if row >= 0:
            index = DESTINATIONS[row][0]
            if self.tabs.selectedTabViewItemIndex() != index:
                self.tabs.setSelectedTabViewItemIndex_(index)
