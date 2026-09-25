from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fourg_bridge.models import RelayStatus

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RelayRecord:
    message_hash: str
    sender: str
    timestamp: str
    status: RelayStatus
    retry_count: int
    next_retry_at: str | None
    locations: tuple[tuple[str, int], ...]
    last_error: str | None = None


class RelayDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self._migrate()
            self._integrity_check()
        except sqlite3.DatabaseError:
            self._quarantine_and_rebuild()

    def get(self, message_hash: str) -> RelayRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT message_hash,sender,timestamp,status,retry_count,next_retry_at,"
                "locations_json,last_error FROM relay WHERE message_hash=?",
                (message_hash,),
            ).fetchone()
        return self._record(row) if row else None

    def create_pending(
        self,
        message_hash: str,
        sender: str,
        timestamp: str,
        locations: tuple[tuple[str, int], ...],
    ) -> RelayRecord:
        locations_json = json.dumps(locations, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO relay"
                "(message_hash,sender,timestamp,status,retry_count,next_retry_at,locations_json)"
                " VALUES(?,?,?,?,0,NULL,?)",
                (message_hash, sender, timestamp, RelayStatus.PENDING, locations_json),
            )
        record = self.get(message_hash)
        if record is None:
            raise sqlite3.DatabaseError("failed to create relay record")
        return record

    def transition(
        self,
        message_hash: str,
        status: RelayStatus,
        *,
        retry_count: int | None = None,
        next_retry_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        assignments = ["status=?", "next_retry_at=?", "last_error=?", "updated_at=?"]
        values: list[object] = [
            status,
            next_retry_at,
            last_error,
            datetime.now(UTC).isoformat(),
        ]
        if retry_count is not None:
            assignments.append("retry_count=?")
            values.append(retry_count)
        values.append(message_hash)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE relay SET {','.join(assignments)} WHERE message_hash=?", values
            )

    def due(self, now: datetime | None = None) -> tuple[RelayRecord, ...]:
        current = (now or datetime.now(UTC)).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT message_hash,sender,timestamp,status,retry_count,next_retry_at,"
                "locations_json,last_error FROM relay "
                "WHERE status IN (?,?) AND (next_retry_at IS NULL OR next_retry_at<=?)",
                (RelayStatus.PENDING, RelayStatus.RETRY, current),
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def cleanup_pending(self) -> tuple[RelayRecord, ...]:
        return self.records_with_status(RelayStatus.CLEANUP_PENDING)

    def records_with_status(self, status: RelayStatus) -> tuple[RelayRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT message_hash,sender,timestamp,status,retry_count,next_retry_at,"
                "locations_json,last_error FROM relay WHERE status=?",
                (status,),
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise sqlite3.DatabaseError("database schema is newer than this app")
            if version == 0:
                connection.executescript(
                    """
                    CREATE TABLE relay (
                        message_hash TEXT PRIMARY KEY,
                        sender TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        status TEXT NOT NULL,
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        next_retry_at TEXT,
                        locations_json TEXT NOT NULL,
                        last_error TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX relay_due_idx ON relay(status, next_retry_at);
                    PRAGMA user_version=1;
                    """
                )

    def _integrity_check(self) -> None:
        with self._connect() as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise sqlite3.DatabaseError(result)

    def _quarantine_and_rebuild(self) -> None:
        if self.path.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            quarantine = self.path.with_suffix(f".corrupt-{stamp}.sqlite")
            shutil.move(self.path, quarantine)
        self._migrate()

    @staticmethod
    def _record(row: tuple[object, ...]) -> RelayRecord:
        return RelayRecord(
            message_hash=str(row[0]),
            sender=str(row[1]),
            timestamp=str(row[2]),
            status=RelayStatus(str(row[3])),
            retry_count=int(str(row[4])),
            next_retry_at=str(row[5]) if row[5] else None,
            locations=tuple((str(item[0]), int(item[1])) for item in json.loads(str(row[6]))),
            last_error=str(row[7]) if row[7] else None,
        )
