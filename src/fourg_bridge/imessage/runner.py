from __future__ import annotations

import re
import subprocess
from pathlib import Path

from fourg_bridge.models import RelayError, RelayResult

_ERROR_NUMBER = re.compile(r"\((-?\d+)\)\s*$")


class AppleScriptRunner:
    def __init__(self, script_path: Path, timeout: float = 15.0) -> None:
        self._script_path = script_path
        self._timeout = timeout

    def run(self, target: str, message: str) -> RelayResult:
        if not self._script_path.is_file():
            return RelayResult(False, RelayError.MESSAGES_UNAVAILABLE, "script resource missing")
        try:
            completed = subprocess.run(
                ["/usr/bin/osascript", str(self._script_path), target, message],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RelayResult(False, RelayError.SCRIPT_TIMEOUT, "AppleScript timed out")
        if completed.returncode == 0 and completed.stdout.strip() == "ACCEPTED":
            return RelayResult(True)
        stderr = completed.stderr.strip()
        number_match = _ERROR_NUMBER.search(stderr)
        number = int(number_match.group(1)) if number_match else None
        mapping = {
            -1743: RelayError.AUTOMATION_DENIED,
            -600: RelayError.MESSAGES_UNAVAILABLE,
            41001: RelayError.IMESSAGE_NOT_CONNECTED,
            41002: RelayError.TARGET_UNAVAILABLE,
        }
        error = (
            mapping.get(number, RelayError.SCRIPT_FAILED)
            if number is not None
            else RelayError.SCRIPT_FAILED
        )
        return RelayResult(False, error, _safe_detail(stderr))


def _safe_detail(detail: str) -> str:
    # Messages may echo user content in an error. Keep only the final error number/name.
    number_match = _ERROR_NUMBER.search(detail)
    return f"AppleScript error {number_match.group(1)}" if number_match else "AppleScript failed"
