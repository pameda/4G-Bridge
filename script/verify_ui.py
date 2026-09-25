"""Verify actual bundled imports, AppKit construction, and all settings pages."""

import subprocess
import sys

result = subprocess.run(
    [sys.argv[1], "--ui-smoke", sys.argv[2]],
    capture_output=True,
    text=True,
    timeout=45,
    check=True,
)
if "UI_SMOKE_OK" not in result.stdout:
    raise SystemExit("Bundled UI failed to finish startup verification")
if "Traceback" in result.stderr or "Unable to simultaneously satisfy" in result.stderr:
    raise SystemExit("Bundled UI reported a runtime or layout error")
print(result.stdout.strip())
