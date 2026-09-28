"""No live network or real payloads leave this test process."""

import json
import subprocess
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fourg_bridge.app.speed_test import SpeedTestController
from fourg_bridge.models import DataState, ModemSnapshot
from fourg_bridge.network.speed_test import (
    PLANS,
    CurlMeasurement,
    Measurement,
    SpeedCancelled,
    SpeedFailure,
    SpeedState,
    SpeedTest,
    curl_arguments,
    measurement,
    resolved_address,
)
from fourg_bridge.network.speed_test import (
    TestMode as Mode,
)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"200 8 0 0 0",
        b"302 8 0 1 .1",
        b"200 nan 0 1 .1",
        b"200 8 0 inf .1",
        b"200 8 0 1 2",
        b"200 4 0 1 .1",
        b"\xff",
    ],
)
def test_invalid_metrics_are_not_bandwidth(raw):
    with pytest.raises(SpeedFailure):
        measurement(raw, 8, 0)


def test_metrics_and_safe_fixed_arguments():
    assert measurement(b"200 8 0 1 .2", 8, 0) == Measurement(8, 0, 1, 0.2)
    args = curl_arguments("download", 8192, "en11")
    assert args[:2] == ["/usr/bin/curl", "-q"]
    assert "if!en11" in args and "-k" not in args and "--location" not in args
    assert args[-1] == "https://speed.cloudflare.com/__down?bytes=8192"
    upload = curl_arguments("upload", 2, None)
    assert "@-" in upload and "--interface" not in upload
    for iface in ("en0;echo", "utun4", "../../file"):
        with pytest.raises(ValueError):
            curl_arguments("download", 1, iface)
    for kind, count in (("arbitrary", 1), ("download", -1), ("download", 1000000000)):
        with pytest.raises(ValueError):
            curl_arguments(kind, count, None)


class Child:
    def __init__(self, replies, code=0):
        self.replies = iter(replies)
        self.returncode = None
        self.code = code
        self.killed = False
        self.inputs = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def communicate(self, input=None, timeout=None):
        self.inputs.append(input)
        if self.killed:
            self.returncode = -9
            return b"", None
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        self.returncode = self.code
        return value, None

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


def fake_child(monkeypatch, replies, code=0):
    child = Child(replies, code)
    factory = Mock(return_value=child)
    monkeypatch.setattr("fourg_bridge.network.speed_test.subprocess.Popen", factory)
    return child, factory


def test_upload_is_random_and_communicate_resumes(monkeypatch):
    child, factory = fake_child(
        monkeypatch, [subprocess.TimeoutExpired("curl", 0.2), b"200 2 8 1 .2"]
    )
    result = CurlMeasurement().perform("upload", 8, "en0", threading.Event(), lambda: True)
    assert result.uploaded == 8
    assert isinstance(child.inputs[0], bytes) and len(child.inputs[0]) == 8
    assert child.inputs[1] is None
    assert factory.call_args.kwargs["stderr"] == subprocess.DEVNULL
    assert "HTTP_PROXY" not in factory.call_args.kwargs["env"]


@pytest.mark.parametrize("reason", ["user", "guard", "timeout"])
def test_running_process_killed_on_stop(monkeypatch, reason):
    child, _ = fake_child(monkeypatch, [subprocess.TimeoutExpired("curl", 0.2)])
    cancellation = threading.Event()
    calls = 0

    def allowed():
        nonlocal calls
        calls += 1
        if calls == 3 and reason == "user":
            cancellation.set()
        return not (calls == 3 and reason == "guard")

    if reason == "timeout":
        clock = iter([0, 1, 20])
        monkeypatch.setattr("fourg_bridge.network.speed_test.time.monotonic", lambda: next(clock))
    with pytest.raises(SpeedFailure):
        CurlMeasurement().perform("download", 8, "en0", cancellation, allowed)
    assert child.killed


def test_cancel_before_spawn(monkeypatch):
    _, factory = fake_child(monkeypatch, [])
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(SpeedCancelled):
        CurlMeasurement().perform("download", 8, None, cancelled, lambda: True)
    factory.assert_not_called()


@pytest.mark.parametrize("output,code", [(b"", 28), (b"garbage", 0), (b"200 2048 8 1 .2", 0)])
def test_network_error_or_unbounded_response(monkeypatch, output, code):
    fake_child(monkeypatch, [output], code)
    with pytest.raises(SpeedFailure):
        CurlMeasurement().perform("upload", 8, None, threading.Event(), lambda: True)


def test_pipeline_progress_units_and_no_retry():
    calls, updates = [], []

    def perform(kind, size, *args):
        calls.append(kind)
        return Measurement(
            size if kind == "download" else 0, size if kind == "upload" else 0, 2, 0.12
        )

    engine = SpeedTest(SimpleNamespace(perform=perform, prepare=lambda *args: None))
    result = engine.run(PLANS[0], "en0", "Wi-Fi", threading.Event(), lambda: True, updates.append)
    assert calls == ["latency"] * 3 + ["download", "upload"]
    assert result.phase == "complete" and result.payload_bytes == PLANS[0].payload
    assert result.download_mbps == PLANS[0].download * 8 / 2 / 1000000
    assert result.latency_ms == 120 and result.jitter_ms == 0
    assert updates[0].running and not updates[-1].running
    transport = Mock()
    transport.perform.side_effect = SpeedFailure("fixed")
    result = SpeedTest(transport).run(
        PLANS[0], None, "current", threading.Event(), lambda: True, updates.append
    )
    assert result.phase == "failed" and result.download_mbps is None
    assert transport.perform.call_count == 1
    transport.perform.side_effect = SpeedCancelled("stopped")
    assert (
        SpeedTest(transport)
        .run(PLANS[0], None, "current", threading.Event(), lambda: True, updates.append)
        .phase
        == "cancelled"
    )
    with pytest.raises(ValueError):
        engine.run(
            replace(PLANS[0], download=1),
            None,
            "x",
            threading.Event(),
            lambda: True,
            updates.append,
        )


def app_fixture():
    budget = SimpleNamespace(
        key="synthetic-sim",
        approved=False,
        status=lambda: SimpleNamespace(state="ready", used=0, total=1024**3),
    )
    app = SimpleNamespace(
        diagnostic_mode=False,
        _query_suspended=False,
        _data_epoch=1,
        _auto_data=SimpleNamespace(error=False, carrier_budget=budget),
        current_snapshot=lambda: ModemSnapshot(data_state=DataState.ON, interface="en11"),
        _show_alert=Mock(),
        _settings_window=SimpleNamespace(refresh=Mock()),
    )
    return app


@pytest.mark.parametrize("change", ["epoch", "sleep", "quota", "sim", "disabled", "error"])
def test_live_guard_rejects_network_or_quota_change(change):
    app = app_fixture()
    controller = SpeedTestController(app)
    assert controller.permitted(Mode.CELLULAR, 1, "synthetic-sim", True)
    if change == "epoch":
        app._data_epoch = 2
    elif change == "sleep":
        app._query_suspended = True
    elif change == "quota":
        app._auto_data.carrier_budget.status = lambda: SimpleNamespace(state="locked")
    elif change == "sim":
        app._auto_data.carrier_budget.key = "other"
    elif change == "disabled":
        app.current_snapshot = lambda: ModemSnapshot()
    else:
        app._auto_data.error = True
    assert not controller.permitted(Mode.CELLULAR, 1, "synthetic-sim", True)


@pytest.mark.parametrize("problem", ["wifi", "cellular", "headroom", "cancel", "modal_change"])
def test_start_never_enables_data_and_requires_consent(monkeypatch, problem):
    import AppKit

    app = app_fixture()
    controller = SpeedTestController(app)
    mode = Mode.WIFI if problem == "wifi" else Mode.CELLULAR
    monkeypatch.setattr(
        "fourg_bridge.app.speed_test.WiFiProbe", lambda: SimpleNamespace(interface=lambda: None)
    )
    if problem == "cellular":
        app.current_snapshot = lambda: ModemSnapshot()
    if problem == "headroom":
        app._auto_data.carrier_budget.status = lambda: SimpleNamespace(
            state="ready", used=0, total=1
        )
    alert = Mock()
    alert.runModal.return_value = AppKit.NSAlertSecondButtonReturn
    if problem == "modal_change":

        def change():
            app._data_epoch = 2
            return AppKit.NSAlertFirstButtonReturn

        alert.runModal.side_effect = change
    factory = Mock()
    factory.alloc.return_value.init.return_value = alert
    monkeypatch.setattr("fourg_bridge.app.speed_test.AppKit.NSAlert", factory)
    controller.start(mode, 0)
    assert not controller.busy
    controller.cancel()
    assert controller.cancelled.is_set()
    controller.update(SpeedState(phase="failed"))
    app._settings_window.refresh.assert_called()


@pytest.mark.parametrize("route_error", [False, True])
def test_worker_completes_or_clears_busy_on_route_failure(monkeypatch, route_error):
    import AppKit

    app = app_fixture()
    app.current_snapshot = lambda: ModemSnapshot(data_state=DataState.OFF)
    controller = SpeedTestController(app)
    alert = Mock()
    alert.runModal.return_value = AppKit.NSAlertFirstButtonReturn
    factory = Mock()
    factory.alloc.return_value.init.return_value = alert
    monkeypatch.setattr("fourg_bridge.app.speed_test.AppKit.NSAlert", factory)
    monkeypatch.setattr(
        "fourg_bridge.app.speed_test.threading.Thread",
        lambda **kw: SimpleNamespace(start=kw["target"]),
    )
    monkeypatch.setattr("fourg_bridge.app.speed_test.AppHelper.callAfter", lambda f, *a: f(*a))
    route = Mock(return_value="en0", side_effect=OSError if route_error else None)
    monkeypatch.setattr("fourg_bridge.app.speed_test.ECMDetector.default_interface", route)

    def run(plan, interface, label, cancelled, allowed, publish):
        assert allowed() and interface is None
        publish(SpeedState(phase="done", download_mbps=10))

    monkeypatch.setattr("fourg_bridge.app.speed_test.SpeedTest", lambda: SimpleNamespace(run=run))
    controller.start(Mode.CURRENT, 0)
    assert not controller.busy
    assert controller.state.phase == ("failed" if route_error else "done")


def dns_reply(address="1.1.1.1", host="speed.cloudflare.com."):
    return json.dumps(
        {
            "Status": 0,
            "Question": [{"name": host, "type": 1}],
            "Answer": [{"name": host, "type": 1, "data": address}],
        }
    ).encode()


@pytest.mark.parametrize(
    "output",
    [
        b"{}",
        b"[]",
        b"x" * 4097,
        dns_reply("198.18.6.1"),
        dns_reply("127.0.0.1"),
        dns_reply(host="other.invalid"),
        dns_reply("bad"),
    ],
)
def test_resolver_rejects_fake_private_or_unrelated_answers(output):
    with pytest.raises(SpeedFailure):
        resolved_address(output)


def test_system_route_resolver_and_bound_measurement_address(monkeypatch):
    assert resolved_address(dns_reply()) == "1.1.1.1"
    transport = CurlMeasurement()
    _, factory = fake_child(monkeypatch, [dns_reply()])
    transport.prepare("en11", threading.Event(), lambda: True)
    args = factory.call_args.args[0]
    assert "--interface" not in args and "--resolve" not in args
    assert args[-1] == "https://cloudflare-dns.com/dns-query?name=speed.cloudflare.com&type=A"
    assert args[args.index("--max-filesize") + 1] == "4096"
    _, factory = fake_child(monkeypatch, [b"200 8 0 1 .2"])
    transport.perform("download", 8, "en11", threading.Event(), lambda: True)
    assert "speed.cloudflare.com:443:1.1.1.1" in factory.call_args.args[0]
    assert "if!en11" in factory.call_args.args[0]
    transport.prepare(None, threading.Event(), lambda: True)
    assert transport.address is None


def test_resolver_failure_never_downloads_or_falls_back(monkeypatch):
    _, factory = fake_child(monkeypatch, [b""], code=28)
    result = SpeedTest().run(
        PLANS[0], "en11", "4G", threading.Event(), lambda: True, lambda _: None
    )
    assert result.phase == "failed" and "解析" in result.note and result.payload_bytes == 0
    assert factory.call_count == 1
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(SpeedCancelled):
        CurlMeasurement().prepare("en11", cancelled, lambda: True)
