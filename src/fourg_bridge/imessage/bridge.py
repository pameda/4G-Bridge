from __future__ import annotations

from datetime import datetime

from fourg_bridge.imessage.formatter import format_relay, format_test_message
from fourg_bridge.imessage.runner import AppleScriptRunner
from fourg_bridge.models import RelayError, RelayResult


class MessagesBridge:
    def __init__(self, runner: AppleScriptRunner, target_provider: object) -> None:
        self._runner = runner
        self._target_provider = target_provider

    def relay(self, sender: str, timestamp: datetime, body: str) -> RelayResult:
        target = self._get_target()
        if not target:
            return RelayResult(False, RelayError.TARGET_UNAVAILABLE, "relay target is empty")
        return self._runner.run(target, format_relay(sender, timestamp, body))

    def send_test(self) -> RelayResult:
        target = self._get_target()
        if not target:
            return RelayResult(False, RelayError.TARGET_UNAVAILABLE, "relay target is empty")
        return self._runner.run(target, format_test_message())

    def _get_target(self) -> str | None:
        getter = getattr(self._target_provider, "get_target", None)
        if not callable(getter):
            return None
        value = getter()
        return str(value).strip() if value else None
