"""Persistent, fail-closed metered-data allowance. Stores counters only."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    used: int
    limit: int
    locked: bool

    @property
    def available(self) -> bool:
        return self.limit > 0 and not self.locked and self.used < self.limit


class BudgetStore:
    """A cap latch survives config changes, month rollover, USB and app restarts.

    Manual grant starts another explicitly authorized allowance; it does not
    erase the independent daily/monthly traffic ledger. No unlimited bypass.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), "
                "used INTEGER NOT NULL, locked INTEGER NOT NULL, month TEXT NOT NULL, "
                "interface TEXT, boot TEXT, rx INTEGER, tx INTEGER)"
            )
            db.execute("INSERT OR IGNORE INTO budget VALUES(1,0,0,'',NULL,NULL,NULL,NULL)")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("budget integrity check failed")
        path.chmod(0o600)

    def status(self, limit: int) -> BudgetStatus:
        with self._lock, closing(sqlite3.connect(self.path)) as db, db:
            used, locked = db.execute("SELECT used,locked FROM budget WHERE id=1").fetchone()
            if limit > 0 and used >= limit:
                locked = 1
                db.execute("UPDATE budget SET locked=1 WHERE id=1")
            return BudgetStatus(used, limit, bool(locked))

    def observe(
        self,
        interface: str,
        boot: str,
        rx: int,
        tx: int,
        limit: int,
        *,
        monthly: bool = False,
        now: datetime | None = None,
    ) -> BudgetStatus:
        if rx < 0 or tx < 0:
            raise ValueError("negative interface counter")
        month = (now or datetime.now().astimezone()).strftime("%Y-%m")
        with self._lock, closing(sqlite3.connect(self.path)) as db, db:
            used, locked, old_month, old_if, old_boot, old_rx, old_tx = db.execute(
                "SELECT used,locked,month,interface,boot,rx,tx FROM budget WHERE id=1"
            ).fetchone()
            # Latch BEFORE rollover: even a threshold change cannot unlock it.
            locked = bool(locked or (limit > 0 and used >= limit))
            if monthly and old_month != month and not locked:
                used = 0
            if old_if == interface and old_boot == boot:
                # Counter reset: all bytes since reset are conservatively counted.
                used += rx - old_rx if rx >= old_rx else rx
                used += tx - old_tx if tx >= old_tx else tx
            locked = bool(locked or (limit > 0 and used >= limit))
            db.execute(
                "UPDATE budget SET used=?,locked=?,month=?,interface=?,boot=?,rx=?,tx=? WHERE id=1",
                (used, int(locked), month, interface, boot, rx, tx),
            )
            return BudgetStatus(used, limit, locked)

    def grant(self, limit: int, *, user_confirmed: bool) -> BudgetStatus:
        if not user_confirmed or limit <= 0:
            raise ValueError("explicit finite allowance required")
        with self._lock, closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "UPDATE budget SET used=0,locked=0,month=? WHERE id=1",
                (datetime.now().astimezone().strftime("%Y-%m"),),
            )
        return self.status(limit)
