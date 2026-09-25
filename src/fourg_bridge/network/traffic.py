from __future__ import annotations

import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fourg_bridge.models import TrafficSnapshot


@dataclass(frozen=True, slots=True)
class TrafficUsage:
    today_rx: int = 0
    today_tx: int = 0
    month_rx: int = 0
    month_tx: int = 0


def parse_netstat_counters(output: str, interface: str) -> tuple[int, int]:
    rows = [line.split() for line in output.splitlines() if line.strip()]
    headers: list[str] | None = None
    totals: list[tuple[int, int]] = []
    for row in rows:
        if row and row[0] == "Name":
            headers = row
            continue
        if headers is None or not row or row[0].rstrip("*") != interface:
            continue
        try:
            ibytes = int(row[headers.index("Ibytes")])
            obytes = int(row[headers.index("Obytes")])
            totals.append((ibytes, obytes))
        except (ValueError, IndexError):
            continue
    if not totals:
        raise ValueError(f"no counters for {interface}")
    return max(totals)


class TrafficMonitor:
    def __init__(self) -> None:
        self._previous: TrafficSnapshot | None = None
        self._session_rx = 0
        self._session_tx = 0

    def sample(self, interface: str) -> TrafficSnapshot:
        output = subprocess.run(
            ["/usr/sbin/netstat", "-ibn", "-I", interface],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        rx, tx = parse_netstat_counters(output, interface)
        now = datetime.now().astimezone()
        download = upload = 0.0
        previous = self._previous
        if previous and previous.interface == interface:
            elapsed = max(0.001, (now - previous.sampled_at).total_seconds())
            rx_delta = max(0, rx - previous.rx_bytes)
            tx_delta = max(0, tx - previous.tx_bytes)
            self._session_rx += rx_delta
            self._session_tx += tx_delta
            download = rx_delta / elapsed
            upload = tx_delta / elapsed
        snapshot = TrafficSnapshot(
            interface,
            now,
            rx,
            tx,
            download,
            upload,
            self._session_rx,
            self._session_tx,
        )
        self._previous = snapshot
        return snapshot

    def reset_session(self) -> None:
        self._previous = None
        self._session_rx = 0
        self._session_tx = 0


class TrafficLedger:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._previous: dict[str, tuple[int, int]] = {}
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS usage ("
                "period TEXT PRIMARY KEY, rx_bytes INTEGER NOT NULL, tx_bytes INTEGER NOT NULL)"
            )

    def record(self, snapshot: TrafficSnapshot) -> TrafficUsage:
        previous = self._previous.get(snapshot.interface)
        self._previous[snapshot.interface] = (snapshot.rx_bytes, snapshot.tx_bytes)
        if previous:
            rx_delta = max(0, snapshot.rx_bytes - previous[0])
            tx_delta = max(0, snapshot.tx_bytes - previous[1])
            if rx_delta or tx_delta:
                self._increment(snapshot.sampled_at.strftime("day:%Y-%m-%d"), rx_delta, tx_delta)
                self._increment(snapshot.sampled_at.strftime("month:%Y-%m"), rx_delta, tx_delta)
        return self.usage(snapshot.sampled_at)

    def usage(self, when: datetime | None = None) -> TrafficUsage:
        current = when or datetime.now().astimezone()
        day = self._get(current.strftime("day:%Y-%m-%d"))
        month = self._get(current.strftime("month:%Y-%m"))
        return TrafficUsage(day[0], day[1], month[0], month[1])

    def _increment(self, period: str, rx_delta: int, tx_delta: int) -> None:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(
                "INSERT INTO usage(period,rx_bytes,tx_bytes) VALUES(?,?,?) "
                "ON CONFLICT(period) DO UPDATE SET "
                "rx_bytes=rx_bytes+excluded.rx_bytes,tx_bytes=tx_bytes+excluded.tx_bytes",
                (period, rx_delta, tx_delta),
            )

    def _get(self, period: str) -> tuple[int, int]:
        with closing(sqlite3.connect(self._path)) as connection:
            row = connection.execute(
                "SELECT rx_bytes,tx_bytes FROM usage WHERE period=?", (period,)
            ).fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)
