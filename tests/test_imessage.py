from datetime import UTC, datetime
from unittest.mock import patch

from fourg_bridge.imessage.bridge import MessagesBridge
from fourg_bridge.imessage.formatter import format_relay, format_test_message
from fourg_bridge.imessage.runner import AppleScriptRunner
from fourg_bridge.models import RelayError, RelayResult


class Target:
    def get_target(self):
        return "synthetic-target"


class FakeRunner:
    def __init__(self):
        self.args = None

    def run(self, target, message):
        self.args = target, message
        return RelayResult(True)


def test_formatter() -> None:
    result = format_relay("10086", datetime(2026, 9, 23, 15, 28, tzinfo=UTC), "剩余18GB 📶")
    assert result.startswith("【4G短信】")
    assert "来自：10086" in result
    assert result.endswith("剩余18GB 📶")
    assert format_test_message() == "【4G Bridge】\niMessage 转发测试成功。"


def test_bridge_passes_body_as_argument_not_script(tmp_path) -> None:
    runner = FakeRunner()
    bridge = MessagesBridge(runner, Target())
    body = 'dangerous" & do shell script "touch /tmp/pwned"'
    assert bridge.relay("10086", datetime.now(UTC), body).accepted
    assert body in runner.args[1]


def test_runner_uses_argv_and_maps_denial(tmp_path) -> None:
    script = tmp_path / "relay.applescript"
    script.write_text("on run argv\nend run", encoding="utf-8")
    completed = type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "denied (-1743)"})()
    with patch("subprocess.run", return_value=completed) as run:
        result = AppleScriptRunner(script).run("target", "private")
    assert result.error == RelayError.AUTOMATION_DENIED
    arguments = run.call_args.args[0]
    assert arguments[-2:] == ["target", "private"]
    assert "private" not in script.read_text(encoding="utf-8")


def test_runner_timeout(tmp_path) -> None:
    script = tmp_path / "relay.applescript"
    script.write_text("", encoding="utf-8")
    import subprocess

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("osascript", 1)):
        result = AppleScriptRunner(script).run("target", "body")
    assert result.error == RelayError.SCRIPT_TIMEOUT
