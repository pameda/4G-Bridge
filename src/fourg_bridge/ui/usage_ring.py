"""Accessible carrier-plan ring with shared, presentation-only warning thresholds."""

import AppKit
import objc

from fourg_bridge.support.presentation import usage_style


def usage_color(name):
    return {
        "blue": AppKit.NSColor.systemBlueColor,
        "orange": AppKit.NSColor.systemOrangeColor,
        "red": AppKit.NSColor.systemRedColor,
        "secondary": AppKit.NSColor.secondaryLabelColor,
    }[name]()


class UsageRing(AppKit.NSView):
    def init(self):
        self = objc.super(UsageRing, self).initWithFrame_(((0, 0), (112, 112)))
        if self is None:
            return None
        self.fraction = None
        self.setAccessibilityElement_(True)
        self.setAccessibilityRole_(AppKit.NSAccessibilityImageRole)
        self.value = AppKit.NSTextField.labelWithString_("—")
        self.value.setAlignment_(AppKit.NSTextAlignmentCenter)
        self.value.setFont_(
            AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(23, AppKit.NSFontWeightSemibold)
        )
        self.value.setFrame_(((12, 43), (88, 29)))
        self.addSubview_(self.value)
        self.caption = AppKit.NSTextField.labelWithString_("待查询")
        self.caption.setAlignment_(AppKit.NSTextAlignmentCenter)
        self.caption.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        self.caption.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        self.caption.setFrame_(((12, 29), (88, 16)))
        self.addSubview_(self.caption)
        self.widthAnchor().constraintEqualToConstant_(112).setActive_(True)
        self.heightAnchor().constraintEqualToConstant_(112).setActive_(True)
        return self

    @objc.python_method
    def update(self, usage):
        self.fraction = usage.fraction if usage else None
        style = usage_style(self.fraction)
        value = style.percent
        self.value.setStringValue_(value)
        self.value.setTextColor_(usage_color(style.color))
        self.caption.setStringValue_("已使用" if usage else "待查询")
        self.setAccessibilityLabel_(
            f"套餐估算已使用 {value}，{style.title}"
            if style.stage is not None
            else "尚无可确认的运营商套餐百分比"
        )
        self.setNeedsDisplay_(True)

    def drawRect_(self, _rect):
        AppKit.NSColor.quaternaryLabelColor().setStroke()
        track = AppKit.NSBezierPath.bezierPathWithOvalInRect_(((7, 7), (98, 98)))
        track.setLineWidth_(7)
        track.stroke()
        style = usage_style(self.fraction)
        if style.stage is None or self.fraction <= 0:
            return
        usage_color(style.color).setStroke()
        arc = AppKit.NSBezierPath.bezierPath()
        arc.setLineWidth_(7)
        arc.setLineCapStyle_(AppKit.NSRoundLineCapStyle)
        arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            (56, 56), 49, 90, 90 - 360 * min(self.fraction, 1), True
        )
        arc.stroke()
