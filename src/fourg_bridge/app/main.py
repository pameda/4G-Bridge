from __future__ import annotations

import sys

import AppKit
from PyObjCTools import AppHelper

from fourg_bridge.app.controller import ApplicationController


class AppDelegate(AppKit.NSObject):
    def applicationDidFinishLaunching_(self, _notification) -> None:
        self.controller = ApplicationController()
        if "--settings" in sys.argv:
            self.controller.show_settings()

    def applicationWillTerminate_(self, _notification) -> None:
        if hasattr(self, "controller"):
            self.controller.close()

    def applicationShouldTerminateAfterLastWindowClosed_(self, _application) -> bool:
        return False


def main() -> None:
    if "--ui-smoke" in sys.argv:
        from pathlib import Path

        from fourg_bridge.ui.smoke import run

        run(Path(sys.argv[sys.argv.index("--ui-smoke") + 1]))
        return
    application = AppKit.NSApplication.sharedApplication()
    application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    application.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
