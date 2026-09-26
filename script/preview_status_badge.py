"""Render and check the production menu badge without USB or messaging effects."""

from pathlib import Path

import AppKit

from fourg_bridge.ui.badge_preview import render_badge_preview

if __name__ == "__main__":
    AppKit.NSApplication.sharedApplication()
    output = Path(__file__).resolve().parents[1] / "artifacts" / "menu-badge-preview.png"
    render_badge_preview(output)
    print(output)
