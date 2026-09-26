"""Wi-Fi-only relay regression using the real decode/assemble/dedup pipeline.

Only the USB and Messages boundary are fakes. Never sends a real message.
"""

import subprocess
import threading
from types import SimpleNamespace

import pytest

from fourg_bridge.app.controller import ApplicationController
from fourg_bridge.app.runtime import ModemRuntime
from fourg_bridge.imessage.bridge import MessagesBridge
from fourg_bridge.models import DataState, ModemSnapshot, RawSMSPart, RelayResult, RelayStatus
from fourg_bridge.sms.assembler import SMSAssembler
from fourg_bridge.sms.relay import SMSRelay
from fourg_bridge.storage.database import RelayDatabase
from fourg_bridge.storage.settings import Settings


def test_pdu_relay_with_cellular_data_off(tmp_path):
    payload = "Wi-Fi 转发 📶".encode("utf-16-be")
    raw = RawSMSPart(
        "ME",
        1,
        (bytes.fromhex("000405910180F6000862903251820000") + bytes([len(payload)]) + payload).hex(),
    )
    calls = []
    deleted = []
    runner = SimpleNamespace(
        run=lambda target, text: (calls.append((target, text)) or RelayResult(True))
    )
    bridge = MessagesBridge(runner, SimpleNamespace(get_target=lambda: "test@example.invalid"))
    database = RelayDatabase(tmp_path / "relay.sqlite")
    receiver = SimpleNamespace(
        poll=lambda: (raw,), delete=lambda locations: (deleted.append(locations) or True)
    )
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._data = SimpleNamespace(state=DataState.OFF)
    runtime._receiver = receiver
    runtime._assembler = SMSAssembler()
    runtime._relay = SMSRelay(database, bridge, receiver)
    assert runtime.poll_sms()
    assert len(calls) == len(deleted) == 1
    assert "Wi-Fi 转发 📶" in calls[0][1]
    assert database.records_with_status(RelayStatus.SENT)
    runtime.poll_sms()
    assert len(calls) == 1  # Re-reading the module must not resend.
    assert runtime._data.state == DataState.OFF


def test_diagnostic_ui_never_scans_or_starts_sms_queue():
    app = ApplicationController.__new__(ApplicationController)
    app.diagnostic_mode = True
    app.rescan()  # No runtime, USB, SMS database or worker locks even exist.


@pytest.mark.parametrize("failure", [OSError(), subprocess.TimeoutExpired("ipconfig", 5)])
def test_ecm_telemetry_error_does_not_close_at_channel(failure):
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._data = SimpleNamespace(state=DataState.OFF)
    runtime._controller = SimpleNamespace(snapshot=lambda: ModemSnapshot(default_interface="en0"))

    def network(_snapshot):
        raise failure

    runtime._network_snapshot = network
    snapshot = runtime.snapshot()
    assert snapshot.data_state == DataState.OFF
    assert "短信转发" in snapshot.warning


@pytest.mark.parametrize("target_ready", [True, False])
def test_controller_polls_sms_before_network_status_even_without_4g(monkeypatch, target_ready):
    calls = []
    app = ApplicationController.__new__(ApplicationController)
    app._runtime_lock = threading.RLock()
    app._rescan_lock = threading.Lock()
    app._rescan_lock.acquire()
    app._settings = Settings(relay_enabled=True)  # Auto data disabled and no allowance.
    app._bridge = SimpleNamespace(target_status=lambda: RelayResult(target_ready))
    app._discovery = SimpleNamespace(discover=lambda: object())
    app._runtime = SimpleNamespace(
        poll_sms=lambda: (calls.append("sms") or None),
        snapshot=lambda: (
            calls.append("status")
            or ModemSnapshot(data_state=DataState.OFF, default_interface="en0")
        ),
        traffic_snapshot=None,
        traffic_usage=None,
    )
    monkeypatch.setattr("fourg_bridge.app.controller.AppHelper.callAfter", lambda *a: None)
    monkeypatch.setattr(
        "fourg_bridge.app.controller.AppKit.NSWorkspace",
        SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(runningApplications=lambda: [])),
    )
    app._rescan_worker()
    assert calls == (["sms", "status"] if target_ready else ["status"])
    assert not app._rescan_lock.locked()


@pytest.mark.parametrize(
    "target,accepted", [(None, False), ("invalid", False), ("test@example.invalid", True)]
)
def test_target_prerequisite_does_not_call_messages(target, accepted):
    bridge = MessagesBridge(object(), SimpleNamespace(get_target=lambda: target))
    assert bridge.target_status().accepted is accepted


def test_keychain_prerequisite_failure_does_not_call_messages():
    def locked():
        raise PermissionError("locked")

    bridge = MessagesBridge(object(), SimpleNamespace(get_target=locked))
    assert not bridge.target_status().accepted
