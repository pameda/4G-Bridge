"""Verify actual bundled imports, AppKit construction, and all settings pages."""

import json
import os
import subprocess
import sys

check_env = dict(os.environ)
check_env.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
unicode_check = subprocess.run(
    [sys.argv[1], "--unicode-selftest"],
    env=check_env,
    capture_output=True,
    encoding="utf-8",
    timeout=15,
    check=True,
)
unicode_report = json.loads(unicode_check.stdout)
assert unicode_report["passed"] and not unicode_report["sent"]
print("BUNDLED_UNICODE_OK: " + unicode_report["locale"])

result = subprocess.run(
    [sys.argv[1], "--ui-smoke", sys.argv[2]],
    capture_output=True,
    text=True,
    encoding="utf-8",
    timeout=45,
    check=True,
)
if "UI_SMOKE_OK" not in result.stdout:
    raise SystemExit("Bundled UI failed to finish startup verification")
if "Traceback" in result.stderr or "Unable to simultaneously satisfy" in result.stderr:
    raise SystemExit("Bundled UI reported a runtime or layout error")
print(result.stdout.strip())
