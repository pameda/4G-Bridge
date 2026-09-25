from datetime import UTC, datetime

from fourg_bridge.models import AssembledSMS, RelayError, RelayResult, RelayStatus
from fourg_bridge.sms.relay import SMSRelay
from fourg_bridge.storage.database import RelayDatabase


class FakeBridge:
    def __init__(self, result: RelayResult) -> None:
        self.result = result
        self.calls = 0

    def relay(self, sender, timestamp, body):
        self.calls += 1
        return self.result


class FakeCleaner:
    def __init__(self, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.calls = 0

    def delete(self, locations):
        self.calls += 1
        return self.succeeds


def _message(body: str = "private body") -> AssembledSMS:
    return AssembledSMS(
        "10086",
        datetime(2026, 9, 23, tzinfo=UTC),
        body,
        ("AABB",),
        (("ME", 1),),
    )


def test_success_deletes_only_after_accept(tmp_path) -> None:
    database = RelayDatabase(tmp_path / "relay.sqlite")
    bridge = FakeBridge(RelayResult(True))
    cleaner = FakeCleaner()
    record = SMSRelay(database, bridge, cleaner).enqueue(_message())
    assert record.status == RelayStatus.SENT
    assert bridge.calls == cleaner.calls == 1
    assert b"private body" not in (tmp_path / "relay.sqlite").read_bytes()


def test_failure_retries_without_delete_and_deduplicates(tmp_path) -> None:
    database = RelayDatabase(tmp_path / "relay.sqlite")
    bridge = FakeBridge(RelayResult(False, RelayError.SCRIPT_FAILED))
    cleaner = FakeCleaner()
    relay = SMSRelay(database, bridge, cleaner)
    first = relay.enqueue(_message())
    second = relay.enqueue(_message())
    assert first.status == RelayStatus.RETRY
    assert first.retry_count == 1
    assert second.retry_count == 1
    assert bridge.calls == 1
    assert cleaner.calls == 0


def test_cleanup_pending_never_resends(tmp_path) -> None:
    database = RelayDatabase(tmp_path / "relay.sqlite")
    bridge = FakeBridge(RelayResult(True))
    cleaner = FakeCleaner(False)
    relay = SMSRelay(database, bridge, cleaner)
    record = relay.enqueue(_message())
    assert record.status == RelayStatus.CLEANUP_PENDING
    relay.enqueue(_message())
    assert bridge.calls == 1
    cleaner.succeeds = True
    relay.retry_cleanup()
    assert database.get(record.message_hash).status == RelayStatus.SENT
