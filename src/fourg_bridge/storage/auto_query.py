"""Durable, fail-closed reservations for opt-in SIM-change SMS queries.

Persist intent *before* submitting AT+CMGS. An uncertain result is never retried.
Only local HMAC SIM keys and timestamps are stored, not ICCIDs or SMS content.
"""

from __future__ import annotations

import math
import re
import sqlite3
from contextlib import closing
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
            if (exists and version != 1) or (not exists and version != 0):
                raise ValueError("Unsupported automatic query ledger version")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Invalid automatic query ledger")
            if exists:
                db.execute("SELECT key FROM current_sim WHERE id=1").fetchall()
                db.execute("SELECT key,stamp FROM attempts").fetchall()
            db.execute("CREATE TABLE IF NOT EXISTS current_sim (id INTEGER PRIMARY KEY, key TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts (key TEXT NOT NULL, stamp REAL NOT NULL)"
            )
            db.execute("PRAGMA user_version=1")
        path.chmod(0o600)

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
