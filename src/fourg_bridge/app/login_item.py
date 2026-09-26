"""System-managed login item. No launch scripts, passwords, or bundled helpers."""

import Foundation
import objc


class LoginItem:
    def __init__(self, service=None):
        self._service = service

    def service(self):
        if self._service is None:
            bundle = Foundation.NSBundle.bundleWithPath_(
                "/System/Library/Frameworks/ServiceManagement.framework"
            )
            if not bundle or not bundle.load():
                raise RuntimeError("ServiceManagement unavailable")
            for selector in (b"registerAndReturnError:", b"unregisterAndReturnError:"):
                objc.registerMetaDataForSelector(
                    b"SMAppService",
                    selector,
                    {"arguments": {2: {"type_modifier": b"o", "type": b"^@"}}},
                )
            self._service = objc.lookUpClass("SMAppService").mainAppService()
        return self._service

    def status(self):
        try:
            return int(self.service().status())
        except Exception:
            return -1

    def set_enabled(self, enabled):
        try:
            service = self.service()
            ok, _error = (
                service.registerAndReturnError_(None)
                if enabled
                else service.unregisterAndReturnError_(None)
            )
            return bool(ok), self.status()
        except Exception:
            return False, self.status()
