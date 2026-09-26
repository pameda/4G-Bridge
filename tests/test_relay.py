from datetime import UTC, datetime, timedelta

from fourg_bridge.models import AssembledSMS, CleanupProof, RelayError, RelayResult, RelayStatus
from fourg_bridge.sms.receiver import CleanupResult
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

    def proofs(self, message):
        return (CleanupProof("ME", 1, "a" * 64, "b" * 64),)

    def delete_verified(self, proofs):
        self.calls += 1
        return CleanupResult.DELETED if self.succeeds else CleanupResult.PENDING


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
    relay.retry_cleanup()
    assert database.get(record.message_hash).status == RelayStatus.CLEANUP_PENDING
    cleaner.succeeds = True
    relay.retry_cleanup()
    assert database.get(record.message_hash).status == RelayStatus.SENT


def test_recover_interrupted_marks_delivery_unknown(tmp_path) -> None:
    database = RelayDatabase(tmp_path / "relay.sqlite")
    pending = database.create_pending("hash", "10086", "2026-09-23T00:00:00+00:00", (("ME", 1),))
    database.transition(pending.message_hash, RelayStatus.SENDING)
    relay = SMSRelay(database, FakeBridge(RelayResult(True)), FakeCleaner())
    relay.recover_interrupted()
    assert database.get("hash").status == RelayStatus.DELIVERY_UNKNOWN


def test_retry_budget_stops_after_three_retries(tmp_path) -> None:
    database = RelayDatabase(tmp_path / "relay.sqlite")
    bridge = FakeBridge(RelayResult(False, RelayError.SCRIPT_FAILED))
    relay = SMSRelay(database, bridge, FakeCleaner())
    record = relay.enqueue(_message())
    for _ in range(3):
        database.transition(
            record.message_hash,
            RelayStatus.RETRY,
            retry_count=record.retry_count,
            next_retry_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )
        record = relay.enqueue(_message())
    assert record.status == RelayStatus.FAILED
    assert record.retry_count == 4
    relay.enqueue(_message())
    assert bridge.calls == 4


def test_timeout_retains_sms_and_never_auto_resends(tmp_path):
    database = RelayDatabase(tmp_path / "relay.sqlite")
    bridge = FakeBridge(RelayResult(False, RelayError.SCRIPT_TIMEOUT, delivery_uncertain=True))
    cleaner = FakeCleaner()
    relay = SMSRelay(database, bridge, cleaner)
    record = relay.enqueue(_message())
    assert record.status == RelayStatus.DELIVERY_UNKNOWN
    relay.enqueue(_message())
    assert bridge.calls == 1 and cleaner.calls == 0


def test_cleanup_exception_cannot_erase_accepted_state(tmp_path):
    database = RelayDatabase(tmp_path / "relay.sqlite")

    class BrokenCleaner(FakeCleaner):
        def delete_verified(self, proofs):
            assert database.records_with_status(RelayStatus.CLEANUP_PENDING)
            raise OSError("USB unplugged")

    bridge = FakeBridge(RelayResult(True))
    relay = SMSRelay(database, bridge, BrokenCleaner())
    record = relay.enqueue(_message())
    assert record.status == RelayStatus.CLEANUP_PENDING
    relay.recover_interrupted()
    relay.retry_cleanup()
    relay.enqueue(_message())
    assert bridge.calls == 1
