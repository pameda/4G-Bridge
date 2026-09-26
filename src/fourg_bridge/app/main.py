from __future__ import annotations

import sys

import AppKit
from PyObjCTools import AppHelper

from fourg_bridge.app.controller import ApplicationController


class AppDelegate(AppKit.NSObject):
    def applicationDidFinishLaunching_(self, _notification) -> None:
        diagnostic = "--relay-diagnostics" in sys.argv
        self.controller = ApplicationController(diagnostic_mode=diagnostic)
        if diagnostic:
            self.controller._settings_window._tabs.setSelectedTabViewItemIndex_(2)
        if diagnostic or "--settings" in sys.argv:
            self.controller.show_settings()

    def applicationWillTerminate_(self, _notification) -> None:
        if hasattr(self, "controller"):
            self.controller.close()

    def applicationShouldTerminateAfterLastWindowClosed_(self, _application) -> bool:
        return False


def main() -> None:
    if "--bridge-check" in sys.argv:
        # Intentionally bypass ApplicationController: no USB, polling, send, or cleanup.
        import json
        from importlib import resources
        from pathlib import Path

        from fourg_bridge.imessage.bridge import MessagesBridge
        from fourg_bridge.imessage.runner import AppleScriptRunner
        from fourg_bridge.storage.keychain import KeychainStore

        script = resources.files("fourg_bridge.imessage.resources").joinpath("relay.applescript")
        result = MessagesBridge(AppleScriptRunner(Path(str(script))), KeychainStore()).check()
        print(
            json.dumps({"check_passed": result.accepted, "error": result.error, "sent": False}),
            flush=True,
        )
        return
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
