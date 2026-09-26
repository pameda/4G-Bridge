"""Opaque visual fixtures rendered by the production badge, without device access."""

from dataclasses import replace
from pathlib import Path

import AppKit

from fourg_bridge.models import DataState, DeviceDescriptor, ModemSnapshot
from fourg_bridge.support.status_item import status_item_style
from fourg_bridge.ui.status_badge import make_status_badge


def render_badge_preview(output: Path, *, scale: int = 2) -> None:
    connected = ModemSnapshot(descriptor=DeviceDescriptor(0x2C7C, 0x0125), rssi_dbm=-73)
    samples = (
        ("未连接", ModemSnapshot()),
        ("数据关闭", connected),
        ("正在连接", replace(connected, data_state=DataState.ENABLING)),
        ("信号较弱", replace(connected, data_state=DataState.ON, rssi_dbm=-105)),
        ("数据开启", replace(connected, data_state=DataState.ON)),
        ("保护异常", replace(connected, data_state=DataState.PROTECTION_FAILED)),
    )
    # Reuse each NSImage across appearances, to catch stale theme caching.
    images = [make_status_badge(status_item_style(snapshot)) for _, snapshot in samples]
    bitmap = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(  # noqa: E501 - Objective-C selector
        None, 480 * scale, 260 * scale, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0
    )
    bitmap = bitmap.bitmapImageRepByRetaggingWithColorSpace_(AppKit.NSColorSpace.sRGBColorSpace())
    AppKit.NSGraphicsContext.saveGraphicsState()
    AppKit.NSGraphicsContext.setCurrentContext_(
        AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
    )
    transform = AppKit.NSAffineTransform.transform()
    transform.scaleBy_(scale)
    transform.concat()
    for column, (name, appearance_name, rgb) in enumerate(
        (
            ("浅色菜单栏", AppKit.NSAppearanceNameAqua, (0.96, 0.97, 0.98)),
            ("深色菜单栏", AppKit.NSAppearanceNameDarkAqua, (0.12, 0.14, 0.17)),
            ("选中背景", AppKit.NSAppearanceNameDarkAqua, (0.20, 0.34, 0.52)),
        )
    ):
        appearance = AppKit.NSAppearance.appearanceNamed_(appearance_name)

        def draw_column(column=column, name=name, rgb=rgb):
            AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*rgb, 1).setFill()
            AppKit.NSRectFill(((column * 160, 0), (160, 260)))
            attributes = {
                AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(11),
                AppKit.NSForegroundColorAttributeName: AppKit.NSColor.labelColor(),
            }
            AppKit.NSString.stringWithString_(name).drawAtPoint_withAttributes_(
                (column * 160 + 16, 232), attributes
            )
            for index, ((title, _), image) in enumerate(zip(samples, images, strict=True)):
                y = 194 - index * 33
                image.drawInRect_fromRect_operation_fraction_(
                    ((column * 160 + 16, y), (42, 18)),
                    AppKit.NSZeroRect,
                    AppKit.NSCompositingOperationSourceOver,
                    1,
                )
                AppKit.NSString.stringWithString_(title).drawAtPoint_withAttributes_(
                    (column * 160 + 68, y + 2), attributes
                )

        appearance.performAsCurrentDrawingAppearance_(draw_column)
    AppKit.NSGraphicsContext.restoreGraphicsState()
    output.parent.mkdir(parents=True, exist_ok=True)
    assert bitmap.representationUsingType_properties_(
        AppKit.NSBitmapImageFileTypePNG, {}
    ).writeToFile_atomically_(str(output), True)
    # The real renderer must produce the paired light/dark fills, not black or blank
    # status-button cache snapshots. Coordinates sample inside the top-left badge.
    for x, expected in ((33, (0.90, 0.94, 0.99)), (193, (0.14, 0.23, 0.34))):
        pixel = bitmap.colorAtX_y_(int(x * scale), int((260 - 196) * scale))
        actual = (pixel.redComponent(), pixel.greenComponent(), pixel.blueComponent())
        assert all(abs(a - b) < 0.03 for a, b in zip(actual, expected, strict=True)), (x, actual)
