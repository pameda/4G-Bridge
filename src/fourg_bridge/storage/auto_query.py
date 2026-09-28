"""Durable, fail-closed reservations for opt-in SIM-change SMS queries.

Persist intent *before* submitting AT+CMGS. Uncertain sends are not blindly retried;
an opted-in monthly refresh permits one new query in a later calendar month.
Only local HMAC SIM keys and timestamps are stored, not ICCIDs or SMS content.
"""

from __future__ import annotations

import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from fourg_bridge.cellular.carrier_query import query_pdu
from fourg_bridge.models import ModemSnapshot, RegistrationState, SIMState


def valid_profile(operator: str, number: str, command: str) -> bool:
    if not isinstance(operator, str) or not 1 <= len(operator) <= 64:
        return False
    if operator != operator.strip() or any(ord(char) < 32 for char in operator):
        return False
    try:
        query_pdu(number, command)
    except (ValueError, TypeError):
        return False
    return True


def matches_profile(snapshot: ModemSnapshot, operator: str) -> bool:
    return bool(
        snapshot.descriptor
        and snapshot.sim_state == SIMState.READY
        and snapshot.iccid
        and snapshot.registration == RegistrationState.REGISTERED_HOME
        and snapshot.operator == operator
    )


class AutoQueryLedger:
    """One attempt per observed SIM change, <=1/SIM/day and <=3 total/day.

    Missing-device observations are deliberately not persisted. Replugging,
    restarting, toggling consent and waiting do not create a new SIM change.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        exists = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(path)) as db, db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if (exists and version not in (1, 2, 3)) or (not exists and version != 0):
                raise ValueError("Unsupported automatic query ledger version")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Invalid automatic query ledger")
            if exists:
                db.execute("SELECT key FROM current_sim WHERE id=1").fetchall()
                db.execute("SELECT key,stamp FROM attempts").fetchall()
            if version >= 2:
                db.execute("SELECT key,stamp,resolved FROM refresh").fetchall()
            if version == 3:
                db.execute("SELECT number,command FROM refresh").fetchall()
            db.execute("CREATE TABLE IF NOT EXISTS current_sim (id INTEGER PRIMARY KEY, key TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts (key TEXT NOT NULL, stamp REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS refresh "
                "(key TEXT PRIMARY KEY, stamp REAL NOT NULL, resolved INTEGER NOT NULL, "
                "number TEXT, command TEXT)"
            )
            if version == 2:
                db.execute("ALTER TABLE refresh ADD COLUMN number TEXT")
                db.execute("ALTER TABLE refresh ADD COLUMN command TEXT")
            db.execute("PRAGMA user_version=3")
        path.chmod(0o600)

    def claim_refresh(
        self, key: str, now: float, *, number: str | None = None, command: str | None = None
    ) -> bool:
        """Reserve before sending: >=5h/SIM, <=8/24h overall, no blind retries.

        A lost or unparseable response keeps its reservation unresolved across
        restarts. A later calendar month permits one fresh query under the same
        rate limits; otherwise only a verified reply or explicit manual query recovers.
        """
        if not re.fullmatch(r"[a-f0-9]{64}", key) or not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid refresh reservation")
        if number is not None or command is not None:
            query_pdu(number, command)  # type: ignore[arg-type]
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT stamp,resolved FROM refresh WHERE key=?", (key,)).fetchone()
            new_month = bool(
                row
                and datetime.fromtimestamp(now).strftime("%Y-%m")
                > datetime.fromtimestamp(row[0]).strftime("%Y-%m")
            )
            if row and ((not row[1] and not new_month) or now - row[0] < 5 * 3600):
                return False
            recent = db.execute(
                "SELECT key,stamp FROM attempts WHERE stamp > ?", (now - 86400,)
            ).fetchall()
            if len(recent) >= 8 or any(k == key and now - stamp < 5 * 3600 for k, stamp in recent):
                return False
            db.execute(
                "INSERT OR REPLACE INTO refresh VALUES(?,?,0,?,?)",
                (key, int(now), number, command),
            )
            db.execute("INSERT INTO attempts VALUES(?,?)", (key, now))
            db.execute("DELETE FROM attempts WHERE stamp <= ?", (now - 86400,))
            return True

    def record_manual(self, key: str, now: float, number: str, command: str) -> None:
        """An explicitly confirmed manual send supersedes a failed reservation."""
        if not re.fullmatch(r"[a-f0-9]{64}", key) or not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid manual reservation")
        query_pdu(number, command)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR REPLACE INTO refresh VALUES(?,?,0,?,?)",
                (key, int(now), number, command),
            )
            db.execute("INSERT INTO attempts VALUES(?,?)", (key, now))

    def pending_refresh(self, key: str, now: float) -> tuple[str, float] | None:
        """Restore reply reception, never sending, after an app restart."""
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT number,stamp FROM refresh WHERE key=? AND resolved=0", (key,)
            ).fetchone()
        if row and row[0] in ("10001", "10010", "10086") and 0 <= now - row[1] <= 6 * 3600:
            return row[0], row[1]
        return None

    def complete_refresh(self, key: str, reply_stamp: float) -> None:
        """Only callers with a SIM-bound, fully parsed reply may acknowledge it."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "UPDATE refresh SET resolved=1 WHERE key=? AND stamp<=?",
                (key, reply_stamp),
            )

    def claim(self, key: str, now: float) -> bool:
        if not re.fullmatch(r"[a-f0-9]{64}", key) or not math.isfinite(now) or now <= 0:
            raise ValueError("Invalid automatic query reservation")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT key FROM current_sim WHERE id=1").fetchone()
            if row and row[0] == key:
                return False
            db.execute("INSERT OR REPLACE INTO current_sim VALUES(1, ?)", (key,))
            # Future stamps (clock rollback) continue to count against limits.
            recent = db.execute(
                "SELECT key FROM attempts WHERE stamp > ?", (now - 86400,)
            ).fetchall()
            if len(recent) >= 3 or any(item[0] == key for item in recent):
                return False
            db.execute("INSERT INTO attempts VALUES(?, ?)", (key, now))
            db.execute("DELETE FROM attempts WHERE stamp <= ?", (now - 86400,))
            return True
