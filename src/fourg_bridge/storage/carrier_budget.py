"""Conservative carrier percentage guard; numbers only, no SMS content."""

import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fourg_bridge.cellular.carrier_query import CarrierUsage


@dataclass(frozen=True)
class CarrierBudgetStatus:
    total: int
    used: int
    state: str


class CarrierBudgetStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.approved = False  # Approval lasts only for the current connection.
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS plan (id INTEGER PRIMARY KEY, total INTEGER, "
                "used INTEGER, stamp TEXT, locked INTEGER, iface TEXT, boot TEXT, "
                "rx INTEGER, tx INTEGER)"
            )
            db.execute("INSERT OR IGNORE INTO plan VALUES(1,0,0,'',0,NULL,NULL,NULL,NULL)")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("carrier budget integrity")
        path.chmod(0o600)

    def update_plan(self, usage: CarrierUsage) -> None:
        with self._lock, closing(sqlite3.connect(self.path)) as db, db:
            old_used, stamp, locked = db.execute(
                "SELECT used,stamp,locked FROM plan WHERE id=1"
            ).fetchone()
            if stamp and usage.timestamp <= datetime.fromisoformat(stamp):
                return
            new_month = bool(
                stamp
                and usage.timestamp.strftime("%Y-%m")
                != datetime.fromisoformat(stamp).strftime("%Y-%m")
            )
            used = usage.used_bytes if new_month or not stamp else max(old_used, usage.used_bytes)
            locked = int((locked and not new_month) or used * 100 >= usage.total_bytes * 98)
            db.execute(
                "UPDATE plan SET total=?,used=?,stamp=?,locked=? WHERE id=1",
                (usage.total_bytes, used, usage.timestamp.isoformat(), locked),
            )

    def observe(self, iface: str, boot: str, rx: int, tx: int) -> None:
        if min(rx, tx) < 0:
            raise ValueError("invalid counters")
        with self._lock, closing(sqlite3.connect(self.path)) as db, db:
            total, used, locked, old_if, old_boot, old_rx, old_tx = db.execute(
                "SELECT total,used,locked,iface,boot,rx,tx FROM plan WHERE id=1"
            ).fetchone()
            if old_if == iface and old_boot == boot:
                used += rx - old_rx if rx >= old_rx else rx
                used += tx - old_tx if tx >= old_tx else tx
            locked = int(locked or (total > 0 and used * 100 >= total * 98))
            db.execute(
                "UPDATE plan SET used=?,locked=?,iface=?,boot=?,rx=?,tx=? WHERE id=1",
                (used, locked, iface, boot, rx, tx),
            )

    def status(self, now: datetime | None = None) -> CarrierBudgetStatus:
        with self._lock, closing(sqlite3.connect(self.path)) as db:
            total, used, stamp, locked = db.execute(
                "SELECT total,used,stamp,locked FROM plan WHERE id=1"
            ).fetchone()
        now = now or datetime.now().astimezone()
        if total <= 0 or not stamp:
            state = "unknown"
        elif locked or used * 100 >= total * 98:
            state = "locked"
        elif (
            now.strftime("%Y-%m") != datetime.fromisoformat(stamp).strftime("%Y-%m")
            or not 0 <= (now - datetime.fromisoformat(stamp)).total_seconds() <= 6 * 3600
        ):
            state = "stale"
        elif used * 100 >= total * 80 and not self.approved:
            state = "confirmation"
        else:
            state = "ready"
        return CarrierBudgetStatus(total, used, state)

    def usage(self) -> CarrierUsage | None:
        with self._lock, closing(sqlite3.connect(self.path)) as db:
            total, used, stamp = db.execute(
                "SELECT total,used,stamp FROM plan WHERE id=1"
            ).fetchone()
        return (
            CarrierUsage(
                total, min(used, total), datetime.fromisoformat(stamp), "套餐＋本机新增 · 估算"
            )
            if total and stamp
            else None
        )
