import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from fourg_bridge.imessage.bridge import MessagesBridge
from fourg_bridge.imessage.formatter import format_relay, format_test_message
from fourg_bridge.imessage.runner import AppleScriptRunner
from fourg_bridge.imessage.target import InvalidTarget, normalize_target
from fourg_bridge.models import RelayError, RelayResult


class Target:
    def get_target(self):
        return "test@example.invalid"


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
    assert arguments[-1] == "send"
    assert "target" not in arguments and "private" not in arguments
    assert run.call_args.kwargs["encoding"] == "utf-8"
    assert json.loads(run.call_args.kwargs["input"]) == {"target": "target", "body": "private"}
    assert "private" not in script.read_text(encoding="utf-8")


def test_runner_timeout(tmp_path) -> None:
    script = tmp_path / "relay.applescript"
    script.write_text("", encoding="utf-8")
    import subprocess

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("osascript", 1)):
        result = AppleScriptRunner(script).run("target", "body")
    assert result.error == RelayError.SCRIPT_TIMEOUT
    assert result.delivery_uncertain


def test_target_validation_does_not_guess_country():
    assert normalize_target(" test@example.invalid ") == "test@example.invalid"
    phone = "+" + "1" + "5" * 10
    assert normalize_target(phone[:2] + " (" + phone[2:5] + ") " + phone[5:]) == phone
    for invalid in ("", "1" * 11, "name", "a@b", "test\n@example.invalid"):
        with pytest.raises(InvalidTarget):
            normalize_target(invalid)


def test_keychain_failure_is_not_a_modem_failure():
    class BrokenTarget:
        def get_target(self):
            raise RuntimeError("private error text")

    runner = FakeRunner()
    result = MessagesBridge(runner, BrokenTarget()).send_test()
    assert result.error == RelayError.KEYCHAIN_UNAVAILABLE
    assert runner.args is None
    assert "private" not in result.detail
    assert MessagesBridge(runner, object()).send_test().error == RelayError.TARGET_UNAVAILABLE


def test_invalid_stored_target_does_not_send():
    class NationalTarget:
        def get_target(self):
            return "1" * 11

    runner = FakeRunner()
    assert MessagesBridge(runner, NationalTarget()).check().error == RelayError.TARGET_INVALID
    assert runner.args is None


def test_check_mode_never_uses_send_action(tmp_path):
    script = tmp_path / "relay.applescript"
    script.write_text("", encoding="utf-8")
    completed = type("Completed", (), {"returncode": 0, "stdout": "CHECKED", "stderr": ""})()
    with patch("subprocess.run", return_value=completed) as run:
        assert MessagesBridge(AppleScriptRunner(script), Target()).check().accepted
    assert run.call_args.args[0][-1] == "check"
    assert json.loads(run.call_args.kwargs["input"]) == {
        "target": "test@example.invalid",
        "body": "",
    }


def test_send_marker_and_missing_resource(tmp_path):
    script = tmp_path / "relay.applescript"
    assert AppleScriptRunner(script).check("target").error == RelayError.MESSAGES_UNAVAILABLE
    script.write_text("", encoding="utf-8")
    completed = type(
        "Completed",
        (),
        {"returncode": 1, "stdout": "", "stderr": "BRIDGE_SEND_STARTED\nprivate (-1712)"},
    )()
    with patch("subprocess.run", return_value=completed):
        result = AppleScriptRunner(script).run("target", "body")
    assert result.delivery_uncertain and result.error == RelayError.SCRIPT_TIMEOUT
    assert "private" not in result.detail
    with patch("subprocess.run", side_effect=OSError):
        assert not AppleScriptRunner(script).run("target", "body").delivery_uncertain


def test_script_has_readonly_check_before_send():
    from pathlib import Path

    script = Path("src/fourg_bridge/imessage/resources/relay.applescript").read_text()
    assert script.index('if operation is "check" then return "CHECKED"') < script.index(
        "send messageText"
    )
    assert "service type is iMessage" in script


def test_unicode_bridge_ignores_ascii_default_locale(monkeypatch):
    from pathlib import Path

    # Exercise real osascript, but the fixture has no Messages or networking calls.
    monkeypatch.setattr("subprocess._text_encoding", lambda: "ascii")
    runner = AppleScriptRunner(
        Path("src/fourg_bridge/imessage/resources/unicode_selftest.applescript")
    )
    result = runner.run("fixture@example.invalid", "中文短信 📶")
    assert result.accepted


def test_c_locale_embedded_style_process_preserves_unicode():
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
    source = (
        "from pathlib import Path; "
        "from fourg_bridge.imessage.runner import AppleScriptRunner; "
        "r=AppleScriptRunner(Path('src/fourg_bridge/imessage/resources/'"
        "'unicode_selftest.applescript')); "
        "assert r.run('fixture@example.invalid', "
        "'\\u4e2d\\u6587\\u77ed\\u4fe1 \\U0001f4f6').accepted"
    )
    result = subprocess.run(
        [sys.executable, "-c", source], env=env, capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
