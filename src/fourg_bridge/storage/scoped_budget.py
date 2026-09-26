"""Mac SIM-scoped carrier accounting with conservative first-enrollment rules."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path

from fourg_bridge.cellular.carrier_query import CarrierUsage
from fourg_bridge.storage.backup import backup_database
from fourg_bridge.storage.carrier_budget import CarrierBudgetStatus, CarrierBudgetStore
from fourg_bridge.storage.identity import IdentityStore


class ScopedCarrierBudget:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self.identity = IdentityStore(directory)
        legacy = directory / "carrier-budget.sqlite"
        if legacy.exists() and not any((directory / "backups").glob("carrier-budget-*")):
            backup_database(legacy)
        self._lock = threading.RLock()
        self.key: str | None = None
        self._store: CarrierBudgetStore | None = None
        self._since: datetime | None = None

    def bind(self, iccid: str | None) -> bool:
        key = self.identity.sim(iccid)
        with self._lock:
            if key == self.key:
                return False
            if self._store:
                self._store.approved = False
            self._store = None
            self.key = None
            self._since = None
            if key:
                store = CarrierBudgetStore(self._directory / f"carrier-sim-{key}.sqlite")
                with closing(sqlite3.connect(store.path)) as db, db:
                    db.execute("CREATE TABLE IF NOT EXISTS binding (stamp TEXT NOT NULL)")
                    row = db.execute("SELECT stamp FROM binding").fetchone()
                    if row is None:
                        stamp = datetime.now().astimezone().isoformat()
                        db.execute("INSERT INTO binding VALUES(?)", (stamp,))
                    else:
                        stamp = row[0]
                    db.execute("UPDATE plan SET iface=NULL,boot=NULL,rx=NULL,tx=NULL WHERE id=1")
                self._since = datetime.fromisoformat(stamp)
                self._store, self.key = store, key
            return True

    @property
    def approved(self) -> bool:
        with self._lock:
            return bool(self._store and self._store.approved)

    @approved.setter
    def approved(self, value: bool) -> None:
        with self._lock:
            if self._store:
                self._store.approved = value

    def update_plan(self, usage: CarrierUsage, *, sim_key: str | None = None) -> None:
        with self._lock:
            if (
                self._store
                and sim_key == self.key
                and self._since
                and usage.timestamp >= self._since
            ):
                self._store.update_plan(usage)

    def observe(self, iface: str, boot: str, rx: int, tx: int) -> None:
        with self._lock:
            if self._store:
                self._store.observe(iface, boot, rx, tx)

    def status(self, now: datetime | None = None) -> CarrierBudgetStatus:
        with self._lock:
            return self._store.status(now) if self._store else CarrierBudgetStatus(0, 0, "unknown")

    def usage(self) -> CarrierUsage | None:
        with self._lock:
            return self._store.usage() if self._store else None
