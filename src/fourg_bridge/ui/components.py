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


def group(views):
    box = AppKit.NSBox.alloc().init()
    box.setTitlePosition_(AppKit.NSNoTitle)
    box.setBoxType_(AppKit.NSBoxCustom)
    box.setBorderType_(AppKit.NSNoBorder)
    box.setFillColor_(AppKit.NSColor.controlBackgroundColor())
    box.setCornerRadius_(14)
    box.setContentViewMargins_(AppKit.NSMakeSize(0, 0))
    content = stack(views, spacing=10)
    pin(content, box.contentView(), 20)
    for child in views:
        child.widthAnchor().constraintLessThanOrEqualToAnchor_(content.widthAnchor()).setActive_(
            True
        )
    return box


def section_title(title, icon):
    return stack([symbol(icon, 17), label(title, 13, weight=AppKit.NSFontWeightSemibold)], True, 8)


class PageBackground(AppKit.NSView):
    def drawRect_(self, rect):
        AppKit.NSColor.underPageBackgroundColor().setFill()
        AppKit.NSRectFill(rect)


def page(title, subtitle, groups):
    view = PageBackground.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 820, 620))
    content = stack(
        [
            stack(
                [label(title, 26, weight=AppKit.NSFontWeightBold), label(subtitle, secondary=True)],
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
    return view


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
