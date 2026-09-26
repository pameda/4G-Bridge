"""Reusable native AppKit layout primitives; no modem or persistence dependencies."""

from __future__ import annotations

import AppKit
import objc


def label(text, size=13, secondary=False, weight=None, numeric=False):
    view = AppKit.NSTextField.wrappingLabelWithString_(text)
    font = (
        AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_
        if numeric
        else AppKit.NSFont.systemFontOfSize_weight_
    )
    view.setFont_(font(size, AppKit.NSFontWeightRegular if weight is None else weight))
    view.setTextColor_(
        AppKit.NSColor.secondaryLabelColor() if secondary else AppKit.NSColor.labelColor()
    )
    return view


def symbol(name, size=22, color=None):
    image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    view = AppKit.NSImageView.alloc().init()
    view.setImage_(image)
    view.setContentTintColor_(color or AppKit.NSColor.controlAccentColor())
    view.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
    view.widthAnchor().constraintEqualToConstant_(size).setActive_(True)
    view.heightAnchor().constraintEqualToConstant_(size).setActive_(True)
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
    if not horizontal:
        view.setHuggingPriority_forOrientation_(750, AppKit.NSLayoutConstraintOrientationVertical)
    return view


def columns(views):
    row = stack(views, True, 16)
    row.setDistribution_(AppKit.NSStackViewDistributionFillEqually)
    for view in views[1:]:
        view.heightAnchor().constraintEqualToAnchor_(views[0].heightAnchor()).setActive_(True)
    return row


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


def group(views, *, accent=False, compact=False):
    box = AppKit.NSBox.alloc().init()
    box.setTitlePosition_(AppKit.NSNoTitle)
    box.setBoxType_(AppKit.NSBoxCustom)
    box.setBorderType_(AppKit.NSLineBorder)
    box.setBorderWidth_(0.5)
    box.setBorderColor_(AppKit.NSColor.separatorColor().colorWithAlphaComponent_(0.25))
    box.setFillColor_(
        AppKit.NSColor.controlAccentColor().colorWithAlphaComponent_(0.06)
        if accent
        else AppKit.NSColor.controlBackgroundColor()
    )
    box.setCornerRadius_(12)
    box.setContentViewMargins_(AppKit.NSMakeSize(0, 0))
    content = stack(views, spacing=6 if compact else 10)
    pin(content, box.contentView(), 14 if compact else 20)
    for child in views:
        child.widthAnchor().constraintLessThanOrEqualToAnchor_(content.widthAnchor()).setActive_(
            True
        )
    return box


def section_title(title, icon):
    return stack([symbol(icon, 17), label(title, 13, weight=AppKit.NSFontWeightSemibold)], True, 8)


class PageBackground(AppKit.NSView):
    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        AppKit.NSColor.windowBackgroundColor().setFill()
        AppKit.NSRectFill(rect)


def page(title, subtitle, groups):
    scroll = AppKit.NSScrollView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 820, 700))
    scroll.setDrawsBackground_(False)
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    view = PageBackground.alloc().init()
    view.setTranslatesAutoresizingMaskIntoConstraints_(False)
    scroll.setDocumentView_(view)
    view.widthAnchor().constraintEqualToAnchor_(scroll.contentView().widthAnchor()).setActive_(True)
    view.heightAnchor().constraintGreaterThanOrEqualToAnchor_(
        scroll.contentView().heightAnchor()
    ).setActive_(True)
    content = stack(
        [
            stack(
                [
                    label(title, 25, weight=AppKit.NSFontWeightSemibold),
                    label(subtitle, 12, secondary=True),
                ],
                spacing=6,
            ),
            *groups,
        ],
        spacing=18,
    )
    view.addSubview_(content)
    content.setTranslatesAutoresizingMaskIntoConstraints_(False)
    AppKit.NSLayoutConstraint.activateConstraints_(
        [
            content.leadingAnchor().constraintEqualToAnchor_constant_(view.leadingAnchor(), 28),
            content.trailingAnchor().constraintEqualToAnchor_constant_(view.trailingAnchor(), -28),
            content.topAnchor().constraintEqualToAnchor_constant_(view.topAnchor(), 24),
            content.bottomAnchor().constraintLessThanOrEqualToAnchor_constant_(
                view.bottomAnchor(), -24
            ),
            *[
                item.widthAnchor().constraintEqualToAnchor_(content.widthAnchor())
                for item in groups
            ],
        ]
    )
    bottom = content.bottomAnchor().constraintEqualToAnchor_constant_(view.bottomAnchor(), -24)
    bottom.setPriority_(1)
    bottom.setActive_(True)
    return scroll


def separator():
    view = AppKit.NSBox.alloc().init()
    view.setBoxType_(AppKit.NSBoxSeparator)
    return view


def spread(left, right):
    """A full-width native row with trailing actions and a flexible middle."""
    spacer = AppKit.NSView.alloc().init()
    row = stack([left, spacer, right], True, 10)
    spacer.setContentHuggingPriority_forOrientation_(
        1, AppKit.NSLayoutConstraintOrientationHorizontal
    )
    return row


class SpeedChart(AppKit.NSView):
    """A small accessible graph of measured interface rates, never sample/demo data."""

    def init(self):
        self = objc.super(SpeedChart, self).initWithFrame_(AppKit.NSMakeRect(0, 0, 720, 112))
        if self is None:
            return None
        self._series = ((), ())
        self.heightAnchor().constraintEqualToConstant_(112).setActive_(True)
        self.setAccessibilityElement_(True)
        self.setAccessibilityRole_(AppKit.NSAccessibilityImageRole)
        self.setAccessibilityLabel_("网卡速度趋势，等待采样")
        return self

    @objc.python_method
    def update(self, history):
        self._series = (history.normalized(), history.normalized(True))
        self.setAccessibilityLabel_(f"网卡下载和上传速度趋势，{len(history.samples)} 个采样点")
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):
        width, height = self.bounds().size
        AppKit.NSColor.separatorColor().setStroke()
        grid = AppKit.NSBezierPath.bezierPath()
        for fraction in (0.05, 0.5, 0.95):
            grid.moveToPoint_((0, height * fraction))
            grid.lineToPoint_((width, height * fraction))
        grid.setLineWidth_(0.5)
        grid.stroke()
        for values, color in zip(
            self._series,
            (AppKit.NSColor.systemBlueColor(), AppKit.NSColor.systemTealColor()),
            strict=True,
        ):
            if len(values) < 2:
                continue
            path = AppKit.NSBezierPath.bezierPath()
            for index, value in enumerate(values):
                point = (width * index / (len(values) - 1), 6 + value * (height - 12))
                (path.moveToPoint_ if index == 0 else path.lineToPoint_)(point)
            color.setStroke()
            path.setLineWidth_(2)
            path.stroke()
