import subprocess
from types import SimpleNamespace

import pytest

from fourg_bridge.network.app_traffic import (
    AppTrafficTracker,
    ProcessCounter,
    parse_counters,
    read_counters,
)


def test_parser_keeps_only_process_counters():
    text = (
        ',bytes_in,bytes_out,\n"Demo, App.12",123,456,\ncom.example.App.34,0,3,\n'
        "bad,1,2,\nx.2,bad,2,\nx.3,-1,0,\nshort\n"
    )
    assert parse_counters(text) == (
        ProcessCounter(12, "Demo, App", 123, 456),
        ProcessCounter(34, "com.example.App", 0, 3),
    )
    assert parse_counters(",bytes_out,bytes_in,\nx.1,2,8,")[0].received == 8
    with pytest.raises(ValueError):
        parse_counters("missing columns")


def test_native_reader_never_requests_connections_or_resolves_names(monkeypatch):
    def run(argv, **kw):
        assert argv == ["/usr/bin/nettop", "-P", "-L", "1", "-n", "-x", "-J", "bytes_in,bytes_out"]
        assert kw["timeout"] == 4 and kw["check"]
        return SimpleNamespace(stdout=",bytes_in,bytes_out,\nDemo.1,50,20,")

    monkeypatch.setattr(subprocess, "run", run)
    assert read_counters()[0].name == "Demo"


def test_rates_baseline_reset_disappear_and_pause():
    tracker = AppTrafficTracker()
    first = tracker.sample((ProcessCounter(1, "A", 100, 200),), 10)
    assert first[0].download == first[0].observed_bytes == 0
    second = tracker.sample(
        (ProcessCounter(1, "A", 150, 220), ProcessCounter(2, "B", 1000, 2000)), 15
    )
    assert (second[0].download, second[0].upload, second[0].observed_bytes) == (10, 4, 70)
    reset = tracker.sample((ProcessCounter(1, "A", 1, 2),), 20)
    assert reset[0].observed_bytes == 0
    tracker.pause()
    assert tracker.sample((ProcessCounter(1, "A", 10000, 10000),), 25)[0].download == 0
    assert tracker.sample((), 30) == ()


@pytest.mark.parametrize("now", [0, 10, 40])
def test_no_spike_for_clock_or_observation_gap(now):
    tracker = AppTrafficTracker()
    tracker.sample((ProcessCounter(1, "A", 10, 10),), 10)
    assert tracker.sample((ProcessCounter(1, "A", 100000, 100000),), now)[0].download == 0


def test_pid_name_change_has_new_baseline():
    tracker = AppTrafficTracker()
    tracker.sample((ProcessCounter(1, "Old", 10, 10),), 1)
    assert tracker.sample((ProcessCounter(1, "New", 9999, 9999),), 6)[0].observed_bytes == 0
