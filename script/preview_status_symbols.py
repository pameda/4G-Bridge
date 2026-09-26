"""Render native SF Symbols at menu-bar size on an opaque test sheet.

Offscreen only: no user windows, screen capture, USB or messaging access.
"""

from pathlib import Path

import AppKit

from fourg_bridge.models import DataState, DeviceDescriptor, DeviceState, ModemSnapshot
from fourg_bridge.support.status_item import status_item_style


def main():
    AppKit.NSApplication.sharedApplication()
    canvas = AppKit.NSImage.alloc().initWithSize_((440, 180))
    canvas.lockFocus()
    AppKit.NSColor.whiteColor().setFill()
    AppKit.NSRectFill(((0, 0), (440, 180)))
    titles = ["模块未连接", "待命 · 数据关闭", "信号较弱", "已连接", "数据保护异常"]
    samples = [
        ModemSnapshot(),
        ModemSnapshot(descriptor=DeviceDescriptor(0x2C7C, 0x0125), rssi_dbm=-73),
        ModemSnapshot(
            descriptor=DeviceDescriptor(0x2C7C, 0x0125), rssi_dbm=-105, data_state=DataState.ON
        ),
        ModemSnapshot(
            descriptor=DeviceDescriptor(0x2C7C, 0x0125), rssi_dbm=-73, data_state=DataState.ON
        ),
        ModemSnapshot(device_state=DeviceState.ERROR, data_state=DataState.PROTECTION_FAILED),
    ]
    attributes = {
        AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
            12, AppKit.NSFontWeightMedium
        ),
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.blackColor(),
    }
    for index, (title, snapshot) in enumerate(zip(titles, samples, strict=True)):
        style = status_item_style(snapshot)
        symbol = AppKit.NSImage.imageWithSystemSymbolName_variableValue_accessibilityDescription_(
            style.symbol, style.level, None
        )
        symbol = symbol.imageWithSymbolConfiguration_(
            AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(
                14, AppKit.NSFontWeightRegular
            )
        )
        y = 146 - index * 30
        symbol.drawInRect_fromRect_operation_fraction_(
            ((24, y), (18, 16)),
            AppKit.NSZeroRect,
            AppKit.NSCompositingOperationSourceOver,
            0.55 if style.secondary else 1,
        )
        AppKit.NSString.stringWithString_("4G").drawAtPoint_withAttributes_((48, y), attributes)
        AppKit.NSString.stringWithString_(title).drawAtPoint_withAttributes_((114, y), attributes)
    canvas.unlockFocus()
    bitmap = AppKit.NSBitmapImageRep.imageRepWithData_(canvas.TIFFRepresentation())
    output = Path(__file__).resolve().parents[1] / "artifacts" / "menu-symbol-preview.png"
    bitmap.representationUsingType_properties_(
        AppKit.NSBitmapImageFileTypePNG, {}
    ).writeToFile_atomically_(str(output), True)
    print(output)


if __name__ == "__main__":
    main()
