"""System About panel; version metadata is shared with the app bundle."""

import AppKit

from fourg_bridge import __build__, __version__


def show_about():
    application = AppKit.NSApplication.sharedApplication()
    application.orderFrontStandardAboutPanelWithOptions_(
        {
            "ApplicationName": "4G Bridge",
            "ApplicationVersion": __version__,
            "Version": __build__,
            "Copyright": "Apple Silicon · QDC507\n隐私留在本机",
        }
    )
    application.activateIgnoringOtherApps_(True)
