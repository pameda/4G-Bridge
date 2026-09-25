from __future__ import annotations

import AppKit
from PyObjCTools import AppHelper

from fourg_bridge.app.controller import ApplicationController


class AppDelegate(AppKit.NSObject):
    def applicationDidFinishLaunching_(self, _notification) -> None:
        self.controller = ApplicationController()

    def applicationWillTerminate_(self, _notification) -> None:
        if hasattr(self, "controller"):
            self.controller.close()

    def applicationShouldTerminateAfterLastWindowClosed_(self, _application) -> bool:
        return False


def main() -> None:
    application = AppKit.NSApplication.sharedApplication()
    application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    application.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
