from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from fourg_bridge.app.controller import ApplicationController
from fourg_bridge.app.runtime import ModemRuntime
from fourg_bridge.models import AssembledSMS, RelayError, RelayResult, RelayStatus
from fourg_bridge.sms.inbox import SMSInbox
from fourg_bridge.storage.database import RelayDatabase


@pytest.mark.parametrize("status", list(RelayStatus))
def test_backfill_atomically_preserves_possibly_sent_records(tmp_path, status):
    db = RelayDatabase(tmp_path / "relay.sqlite")
    db.create_pending("key", "synthetic", "t", ())
    db.transition("key", status, retry_count=4, next_retry_at="2099-01-01T00:00:00+00:00")
    eligible = status in (RelayStatus.PENDING, RelayStatus.RETRY, RelayStatus.FAILED)
    assert db.retry_unsent("key") == eligible
    record = db.get("key")
    assert record.status == (RelayStatus.RETRY if eligible else status)
    assert record.retry_count == (0 if eligible else 4)
    assert (record.next_retry_at is None) == eligible


def test_claim_send_wins_over_stale_backfill_snapshot(tmp_path):
    db = RelayDatabase(tmp_path / "relay.sqlite")
    db.create_pending("key", "synthetic", "t", ())
    assert db.get("key").status == RelayStatus.PENDING
    assert db.claim_send("key")
    assert not db.retry_unsent("key")
    assert db.get("key").status == RelayStatus.SENDING
    assert not db.retry_unsent("absent")
    db.blocked = "blocked"
    assert not db.retry_unsent("key")


@pytest.mark.parametrize(
    "same_sim,present,expected", [(True, True, 2), (False, True, 0), (True, False, 0)]
)
def test_backfill_requires_reread_current_sim_and_original_message(
    tmp_path, same_sim, present, expected
):
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._database = RelayDatabase(tmp_path / "relay.sqlite")
    runtime.inbox = SMSInbox()
    runtime._database.create_pending("failed", "synthetic", "t", ())
    runtime._database.transition("failed", RelayStatus.FAILED)
    calls = []

    def poll(*, relay_enabled):
        calls.append(relay_enabled)
        runtime._sms_identity = ("device", "sim" if same_sim else "other-sim")
        runtime._last_sms_hashes = {"failed", "new"} if present else set()

    runtime.poll_sms = poll
    assert runtime.prepare_backfill(("failed", "new", "deleted"), ("device", "sim")) == expected
    assert calls == [False]  # Preflight never sends or cleans up.
    assert runtime.prepare_backfill(("new",), None) == 0
    runtime._database.blocked = "blocked"
    assert runtime.prepare_backfill(("new",), ("device", "sim")) == 0


@pytest.mark.parametrize("status", [None, *RelayStatus])
def test_inbox_backfill_badge_has_same_safety_rules(status):
    inbox = SMSInbox()
    inbox.add(AssembledSMS("synthetic", datetime.now(UTC), "fixture", ("fixture",), ()))
    key = inbox.snapshot()[0].message_hash
    if status is not None:
        inbox.set_status(key, status)
    assert inbox.snapshot()[0].can_backfill == (
        status in (None, RelayStatus.PENDING, RelayStatus.RETRY, RelayStatus.FAILED)
    )


@pytest.mark.parametrize("ready", [False, True])
def test_controller_requires_target_authorization_before_backfill(monkeypatch, ready):
    import threading

    calls = []
    app = ApplicationController.__new__(ApplicationController)
    app._bridge_busy = False
    app.relay_enabled = lambda: True
    app.received_sms = lambda: (SimpleNamespace(message_hash="fixture", can_backfill=True),)
    app._sms_inbox = SimpleNamespace(identity=("device", "sim"))
    app._settings_window = SimpleNamespace(refresh=lambda _: None)
    app._runtime_lock = threading.RLock()
    app._bridge = SimpleNamespace(
        target_status=lambda: RelayResult(ready, RelayError.KEYCHAIN_UNAVAILABLE)
    )
    app._runtime = SimpleNamespace(prepare_backfill=lambda *args: calls.append(args) or 1)
    app._backfill_finished = lambda detail, count: calls.append(count)
    monkeypatch.setattr(
        "fourg_bridge.app.controller.threading.Thread",
        lambda target, **kwargs: SimpleNamespace(start=target),
    )
    monkeypatch.setattr("fourg_bridge.app.controller.AppHelper.callAfter", lambda f, *a: f(*a))
    app.backfill_unsent_sms()
    assert calls == ([(("fixture",), ("device", "sim")), 1] if ready else [0])
