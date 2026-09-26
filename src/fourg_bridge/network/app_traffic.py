"""In-memory process counter observations. No endpoints, packet data or disk history."""

from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessCounter:
    pid: int
    name: str
    received: int
    sent: int


@dataclass(frozen=True, slots=True)
class AppTraffic:
    pid: int
    name: str
    download: float
    upload: float
    observed_bytes: int


def parse_counters(output: str) -> tuple[ProcessCounter, ...]:
    rows = csv.reader(io.StringIO(output))
    header = next(rows, [])
    if "bytes_in" not in header or "bytes_out" not in header:
        raise ValueError("process counter columns unavailable")
    rx, tx = header.index("bytes_in"), header.index("bytes_out")
    result = []
    for row in rows:
        if len(row) <= max(rx, tx):
            continue
        name, separator, pid = row[0].rpartition(".")
        if not separator or not pid.isdecimal() or not name:
            continue
        try:
            received, sent = int(row[rx]), int(row[tx])
        except ValueError:
            continue
        if min(received, sent) < 0:
            continue
        result.append(ProcessCounter(int(pid), name[:128], received, sent))
    return tuple(result)


def read_counters() -> tuple[ProcessCounter, ...]:
    result = subprocess.run(
        ["/usr/bin/nettop", "-P", "-L", "1", "-n", "-x", "-J", "bytes_in,bytes_out"],
        capture_output=True,
        text=True,
        timeout=4,
        check=True,
    )
    return parse_counters(result.stdout)


class AppTrafficTracker:
    def __init__(self) -> None:
        self._previous: dict[tuple[int, str], ProcessCounter] = {}
        self._totals: dict[tuple[int, str], int] = {}
        self._time: float | None = None

    def pause(self) -> None:
        self._previous.clear()
        self._time = None

    def sample(self, counters: tuple[ProcessCounter, ...], now: float) -> tuple[AppTraffic, ...]:
        elapsed = now - self._time if self._time is not None else 0
        current = {(p.pid, p.name): p for p in counters}
        result = []
        for key, p in current.items():
            old = self._previous.get(key)
            rx = tx = 0
            if old and 0 < elapsed <= 20 and p.received >= old.received and p.sent >= old.sent:
                rx, tx = p.received - old.received, p.sent - old.sent
            total = self._totals.get(key, 0) + rx + tx
            if old and (p.received < old.received or p.sent < old.sent):
                total = 0  # Process/counter restart, never invent a throughput spike.
            result.append(
                AppTraffic(
                    p.pid, p.name, rx / elapsed if rx else 0, tx / elapsed if tx else 0, total
                )
            )
        self._previous, self._time = current, now
        self._totals = {(p.pid, p.name): p.observed_bytes for p in result}
        return tuple(
            sorted(result, key=lambda p: (-(p.download + p.upload), -p.observed_bytes, p.name))
        )
