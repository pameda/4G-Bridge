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

        # Use Apple's optical sizing and variable signal symbol instead of hand-drawn glyphs.
        name = "pause.fill" if style.symbol == "cellularbars" and style.secondary else style.symbol
        glyph = AppKit.NSImage.imageWithSystemSymbolName_variableValue_accessibilityDescription_(
            name, style.level, style.description
        )
        configuration = AppKit.NSImageSymbolConfiguration.configurationWithPaletteColors_(
            [foreground]
        )
        glyph = glyph.imageWithSymbolConfiguration_(configuration)
        size = glyph.size()
        scale = min(12 / size.width, 12 / size.height)
        width, height = size.width * scale, size.height * scale
        glyph.drawInRect_fromRect_operation_fraction_(
            ((4 + (12 - width) / 2, (18 - height) / 2), (width, height)),
            AppKit.NSZeroRect,
            AppKit.NSCompositingOperationSourceOver,
            1,
        )
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
