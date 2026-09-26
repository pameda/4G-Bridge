from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from fourg_bridge.models import AssembledSMS, CleanupProof, RelayResult, RelayStatus
from fourg_bridge.sms.receiver import CleanupResult
from fourg_bridge.storage.database import RelayDatabase, RelayRecord
from fourg_bridge.support.privacy import stable_message_hash

_BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))


class BridgeProtocol(Protocol):
    def relay(self, sender: str, timestamp: datetime, body: str) -> RelayResult: ...


class CleanerProtocol(Protocol):
    def proofs(self, message: AssembledSMS) -> tuple[CleanupProof, ...]: ...
    def delete_verified(self, proofs: tuple[CleanupProof, ...]) -> CleanupResult: ...


class SMSRelay:
    def __init__(
        self, database: RelayDatabase, bridge: BridgeProtocol, cleaner: CleanerProtocol
    ) -> None:
        self._database = database
        self._bridge = bridge
        self._cleaner = cleaner

    def enqueue(self, message: AssembledSMS) -> RelayRecord:
        message_hash = stable_message_hash(
            message.sender, message.timestamp.isoformat(), message.ordered_pdus
        )
        record = self._database.create_pending(
            message_hash,
            message.sender,
            message.timestamp.isoformat(),
            message.locations,
            self._cleaner.proofs(message),
        )
        if record.status in (
            RelayStatus.SENT,
            RelayStatus.CLEANUP_PENDING,
            RelayStatus.CLEANUP_BLOCKED,
            RelayStatus.DELIVERY_UNKNOWN,
            RelayStatus.FAILED,
        ):
            return record
        if record.next_retry_at:
            retry_at = datetime.fromisoformat(record.next_retry_at)
            if retry_at > datetime.now(UTC):
                return record
        return self._attempt(record, message)

    def retry_cleanup(self) -> None:
        for record in self._database.cleanup_pending():
            self._cleanup(record)

    def recover_interrupted(self) -> None:
        # SENDING means Messages may have accepted the send before a crash.
        # Never auto-resend: favor duplicate prevention over silent duplication.
        for record in self._database.records_with_status(RelayStatus.SENDING):
            self._database.transition(record.message_hash, RelayStatus.DELIVERY_UNKNOWN)

    def _cleanup(self, record: RelayRecord) -> None:
        try:
            result = (
                self._cleaner.delete_verified(record.cleanup)
                if record.cleanup
                else CleanupResult.BLOCKED
            )
        except Exception:
            result = CleanupResult.PENDING
        status = {
            CleanupResult.DELETED: RelayStatus.SENT,
            CleanupResult.PENDING: RelayStatus.CLEANUP_PENDING,
            CleanupResult.BLOCKED: RelayStatus.CLEANUP_BLOCKED,
        }[result]
        self._database.transition(
            record.message_hash,
            status,
            last_error=None if result == CleanupResult.DELETED else "cleanup_verification_required",
        )

    def _attempt(self, record: RelayRecord, message: AssembledSMS) -> RelayRecord:
        self._database.transition(record.message_hash, RelayStatus.SENDING)
        result = self._bridge.relay(message.sender, message.timestamp, message.body)
        if result.accepted:
            # Persist acceptance before module cleanup, which can fail or raise independently.
            self._database.transition(record.message_hash, RelayStatus.CLEANUP_PENDING)
            self._cleanup(record)
            updated = self._database.get(record.message_hash)
            assert updated is not None
            return updated

        if result.delivery_uncertain:
            self._database.transition(
                record.message_hash, RelayStatus.DELIVERY_UNKNOWN, last_error=result.error
            )
            updated = self._database.get(record.message_hash)
            assert updated is not None
            return updated

        retries = record.retry_count + 1
        if retries > len(_BACKOFF):
            status = RelayStatus.FAILED
            next_retry = None
        else:
            status = RelayStatus.RETRY
            next_retry = (datetime.now(UTC) + _BACKOFF[retries - 1]).isoformat()
        self._database.transition(
            record.message_hash,
            status,
            retry_count=retries,
            next_retry_at=next_retry,
            last_error=result.error,
        )
        updated = self._database.get(record.message_hash)
        assert updated is not None
        return updated
