from datetime import UTC, datetime

from fourg_bridge.models import RelayStatus
from fourg_bridge.storage.database import RelayDatabase


def test_database_stores_no_body_and_transitions(tmp_path) -> None:
    database = RelayDatabase(tmp_path / "relay.sqlite")
    record = database.create_pending("abc", "10086", "2026-09-23", (("ME", 2),))
    assert record.status == RelayStatus.PENDING
    database.transition(
        "abc", RelayStatus.RETRY, retry_count=1, next_retry_at="2026-09-24T00:00:00+00:00"
    )
    updated = database.get("abc")
    assert updated is not None and updated.retry_count == 1
    raw = (tmp_path / "relay.sqlite").read_bytes()
    assert "短信正文".encode() not in raw


def test_due_and_cleanup_queries(tmp_path) -> None:
    database = RelayDatabase(tmp_path / "relay.sqlite")
    database.create_pending("pending", "1", "t", (("ME", 1),))
    database.create_pending("cleanup", "2", "t", (("SM", 2),))
    database.transition("cleanup", RelayStatus.CLEANUP_PENDING)
    due = database.due(datetime.now(UTC))
    assert [record.message_hash for record in due] == ["pending"]
    assert database.cleanup_pending()[0].message_hash == "cleanup"


def test_corrupt_database_is_quarantined(tmp_path) -> None:
    path = tmp_path / "relay.sqlite"
    path.write_bytes(b"not a database")
    database = RelayDatabase(path)
    assert database.get("missing") is None
    assert database.blocked
    assert path.read_bytes() == b"not a database"
    assert list(tmp_path.glob("backups/relay-*/relay.sqlite"))
