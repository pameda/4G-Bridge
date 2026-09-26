"""Resolution-independent menu-bar badge; no captured screen or bitmap assets."""

import AppKit

from fourg_bridge.support.status_item import StatusItemStyle, badge_palette

BADGE_SIZE = (42, 18)
STATUS_ITEM_WIDTH = 50


def make_status_badge(style: StatusItemStyle):
    def draw(_rect):
        appearance = AppKit.NSAppearance.currentDrawingAppearance()
        dark = (
            appearance.bestMatchFromAppearancesWithNames_(
                [AppKit.NSAppearanceNameAqua, AppKit.NSAppearanceNameDarkAqua]
            )
            == AppKit.NSAppearanceNameDarkAqua
        )
        palette = badge_palette(style, dark=dark)
        foreground = AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*palette.foreground, 1)
        background = AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*palette.background, 1)
        background.setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            ((0, 0), BADGE_SIZE), 5, 5
        ).fill()
        foreground.setFill()
        foreground.setStroke()

        if style.symbol == "cellularbars" and not style.secondary:
            for index, height in enumerate((3, 5, 7, 10)):
                foreground.colorWithAlphaComponent_(
                    1 if index < style.level * 4 else 0.30
                ).setFill()
                AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    ((4 + index * 3, 4), (2, height)), 1, 1
                ).fill()
        elif style.symbol == "cable.connector":
            ring = AppKit.NSBezierPath.bezierPathWithOvalInRect_(((5, 5), (8, 8)))
            ring.setLineWidth_(1.3)
            ring.stroke()
            slash = AppKit.NSBezierPath.bezierPath()
            slash.moveToPoint_((5.5, 5.5))
            slash.lineToPoint_((12.5, 12.5))
            slash.setLineWidth_(1.3)
            slash.stroke()
        elif style.symbol == "exclamationmark.triangle":
            AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                ((8, 8), (2, 6)), 1, 1
            ).fill()
            AppKit.NSBezierPath.bezierPathWithOvalInRect_(((8, 4), (2, 2))).fill()
        elif style.symbol == "arrow.triangle.2.circlepath":
            for x in (6, 11):
                AppKit.NSBezierPath.bezierPathWithOvalInRect_(((x, 8), (2.5, 2.5))).fill()
        else:
            # Paused bars distinguish data OFF from a merely weak active signal.
            for x in (6, 11):
                AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    ((x, 5), (2, 8)), 1, 1
                ).fill()
        attributes = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                11, AppKit.NSFontWeightSemibold
            ),
            AppKit.NSForegroundColorAttributeName: foreground,
        }
        text = AppKit.NSString.stringWithString_("4G")
        size = text.sizeWithAttributes_(attributes)
        text.drawAtPoint_withAttributes_((19, (18 - size.height) / 2), attributes)
        return True

    image = AppKit.NSImage.imageWithSize_flipped_drawingHandler_(BADGE_SIZE, False, draw)
    # Let AppKit draw at the display's pixel scale and current menu-bar appearance.
    # Never cache a light-mode rendering for later reuse on a dark menu bar.
    image.setCacheMode_(AppKit.NSImageCacheNever)
    image.setTemplate_(False)
    image.setAccessibilityDescription_("4G Bridge · " + style.description)
    return image
