"""Controller authorization and recovery actions never send implicitly."""

from types import SimpleNamespace

from fourg_bridge.app.controller import ApplicationController
from fourg_bridge.models import RelayError, RelayResult, RelayStatus
from fourg_bridge.storage.database import RelayDatabase
from fourg_bridge.storage.settings import Settings
from fourg_bridge.support.event_log import EventLog


def controller(monkeypatch, tmp_path):
    app = ApplicationController.__new__(ApplicationController)
    app.diagnostic_mode = False
    app._bridge_busy = False
    app._events = EventLog()
    app._settings = Settings(relay_enabled=True)
    app._database = RelayDatabase(tmp_path / "relay.sqlite")
    app._settings_window = SimpleNamespace(refresh=lambda *args: None)
    app._show_alert = lambda *args: None
    monkeypatch.setattr(
        "fourg_bridge.app.controller.AppHelper.callAfter", lambda fn, *args: fn(*args)
    )
    monkeypatch.setattr(
        "fourg_bridge.app.controller.threading.Thread",
        lambda *, target, **kw: SimpleNamespace(start=target),
    )
    return app


def test_authorization_checks_connection_without_sending(monkeypatch, tmp_path):
    app = controller(monkeypatch, tmp_path)
    calls = []
    app._keychain = SimpleNamespace(
        get_target=lambda **kw: calls.append(kw) or "test@example.invalid"
    )
    app._bridge = SimpleNamespace(check=lambda: calls.append("check") or RelayResult(True))
    app.authorize_relay_target()
    assert calls == [{"allow_interaction": True}, "check"]
    assert not app._bridge_busy
    assert app.relay_health() == "连接检查通过"


def test_failed_save_retains_input_and_releases_busy(monkeypatch, tmp_path):
    app = controller(monkeypatch, tmp_path)
    refreshes = []
    app._settings_window.refresh = lambda include: refreshes.append(include)

    def fail(value):
        raise RuntimeError("do not expose target")

    app._keychain = SimpleNamespace(set_target=fail)
    assert app.set_relay_target("test@example.invalid")
    assert not app._bridge_busy
    assert refreshes == [False, False]
    assert "输入内容已保留" in app._bridge_status
    assert "test@example.invalid" not in app._bridge_status


def test_manual_failed_retry_preserves_uncertain_messages(monkeypatch, tmp_path):
    app = controller(monkeypatch, tmp_path)
    for key, status in [("failed", RelayStatus.FAILED), ("unknown", RelayStatus.DELIVERY_UNKNOWN)]:
        app._database.create_pending(key, "10086", "2026-09-27T00:00:00+00:00", ())
        app._database.transition(key, status, retry_count=4)
    scans = []
    app.rescan = lambda: scans.append(True)
    app.retry_failed_relay()
    assert app._database.get("unknown").status == RelayStatus.DELIVERY_UNKNOWN
    assert app._database.get("failed").status == RelayStatus.RETRY
    assert app._database.get("failed").retry_count == 0
    assert scans == [True]
    assert "不确定" in app.relay_health()


def test_uncertain_test_displays_and_keeps_safe_error_code(monkeypatch, tmp_path):
    app = controller(monkeypatch, tmp_path)
    app._bridge_finished(
        RelayResult(False, RelayError.SCRIPT_FAILED, "AppleScript error -10000", True), True
    )
    assert "-10000" in app._bridge_status
    assert "-10000" in app._events.text(True)
    assert not app._bridge_busy
    assert "发送结果不确定" in app.relay_health()
