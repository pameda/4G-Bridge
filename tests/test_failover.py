from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from fourg_bridge.network.connectivity import WiFiProbe
from fourg_bridge.network.ecm import ECMDetector
from fourg_bridge.network.failover import Action, FailoverPolicy, Observation
from fourg_bridge.storage.budget import BudgetStore
from fourg_bridge.storage.settings import Settings, SettingsStore

DOWN = Observation(True, True, True, False, False)


def test_debounce_and_wifi_recovery():
    policy = FailoverPolicy()
    assert [policy.decide(DOWN) for _ in range(3)] == [Action.HOLD, Action.HOLD, Action.ENABLE]
    policy.completed(Action.ENABLE, True)
    assert policy.owned
    up = replace(DOWN, data_on=True, wifi_online=True)
    assert policy.decide(up) == Action.HOLD
    assert policy.decide(up) == Action.DISABLE
    policy.completed(Action.DISABLE, True)
    assert not policy.owned


@pytest.mark.parametrize("field", ["vpn_active", "other_default"])
def test_never_reorders_vpn_or_other_default(field):
    policy = FailoverPolicy()
    blocked = replace(DOWN, **{field: True})
    assert all(policy.decide(blocked) == Action.HOLD for _ in range(5))
    policy.completed(Action.ENABLE, True)
    assert policy.decide(replace(blocked, data_on=True)) == Action.DISABLE


def test_cap_blocks_even_manual_data_and_disabled_policy():
    policy = FailoverPolicy()
    assert policy.decide(replace(DOWN, budget_available=False)) == Action.HOLD
    assert policy.decide(replace(DOWN, budget_available=False, data_on=True)) == Action.DISABLE
    assert policy.decide(replace(DOWN, enabled=False)) == Action.HOLD
    assert policy.decide(replace(DOWN, device_available=False)) == Action.HOLD
    assert policy.decide(replace(DOWN, wifi_online=None)) == Action.HOLD
    policy.completed(Action.ENABLE, False)
    assert policy.paused
    assert all(policy.decide(DOWN) == Action.HOLD for _ in range(10))
    policy.owned = True
    assert policy.decide(replace(DOWN, data_on=True, enabled=False)) == Action.DISABLE


def test_no_flapping_or_manual_session_takeover():
    policy = FailoverPolicy()
    for _ in range(5):
        assert policy.decide(DOWN) == Action.HOLD
        assert policy.decide(replace(DOWN, wifi_online=True)) == Action.HOLD
    for _ in range(5):
        assert policy.decide(replace(DOWN, data_on=True, wifi_online=True)) == Action.HOLD
    policy.completed(Action.DISABLE, False)


def test_budget_latch_survives_restart_interface_and_month(tmp_path):
    path = tmp_path / "budget.sqlite"
    store = BudgetStore(path)
    sept = datetime(2026, 9, 30)
    oct_ = datetime(2026, 10, 1)
    assert not store.status(0).available
    assert store.observe("en1", "boot", 100, 100, 100, now=sept).available
    status = store.observe("en1", "boot", 160, 140, 100, now=sept)
    assert status.locked and status.used == 100
    store = BudgetStore(path)
    assert store.status(1000).locked  # Raising the cap cannot clear a latch.
    assert store.observe("en8", "boot2", 0, 0, 1000, monthly=True, now=oct_).locked
    assert store.status(1000).used == 100
    with pytest.raises(ValueError):
        store.grant(1000, user_confirmed=False)
    with pytest.raises(ValueError):
        store.grant(0, user_confirmed=True)
    assert store.grant(1000, user_confirmed=True).available
    assert store.status(1000).used == 0


def test_budget_rollover_reset_and_counter_reset(tmp_path):
    store = BudgetStore(tmp_path / "budget.sqlite")
    sept = datetime(2026, 9, 30)
    oct_ = datetime(2026, 10, 1)
    store.observe("en0", "boot", 100, 200, 1000, now=sept)
    assert store.observe("en0", "boot", 130, 240, 1000, now=sept).used == 70
    assert store.observe("en0", "boot", 10, 20, 1000, now=sept).used == 100
    assert store.observe("en0", "boot", 20, 40, 1000, monthly=True, now=oct_).used == 30
    assert store.status(30).locked
    with pytest.raises(ValueError):
        store.observe("en0", "boot", -1, 0, 1000)


def test_budget_corruption_is_not_silently_reset(tmp_path):
    import sqlite3

    path = tmp_path / "budget.sqlite"
    path.write_bytes(b"broken")
    with pytest.raises(sqlite3.DatabaseError):
        BudgetStore(path)
    assert path.read_bytes() == b"broken"


def test_settings_never_enable_auto_without_explicit_boolean(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert not store.load().auto_data_enabled
    settings = Settings(auto_data_enabled=True, data_limit_bytes=1000, data_budget_period="month")
    store.save(settings)
    assert store.load() == settings
    store.path.write_text('{"auto_data_enabled":"yes", "data_limit_bytes":-5}')
    assert store.load().data_limit_bytes == 0
    assert not store.load().auto_data_enabled


def test_probes_bind_wifi_bypass_proxy_and_limit_bytes(monkeypatch):
    monkeypatch.setattr(ECMDetector, "_run", lambda *a: "Hardware Port: Wi-Fi\nDevice: en5\n")
    monkeypatch.setattr(ECMDetector, "ipv4", lambda _: "192.0.2.2")
    calls = []

    def run(args, **kw):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=b"<BODY>Success</BODY>")

    monkeypatch.setattr("subprocess.run", run)
    probe = WiFiProbe()
    assert probe.interface() == "en5"
    assert probe.online("en5")
    assert calls[0][1] == "-q"  # Ignore ~/.curlrc.
    assert "if!en5" in calls[0] and "--max-filesize" in calls[0]
    assert "--noproxy" in calls[0]
    assert not probe.online(None)
    monkeypatch.setattr(ECMDetector, "ipv4", lambda _: None)
    assert not probe.online("en5")


def test_probe_failure_portal_and_second_endpoint(monkeypatch):
    import subprocess

    monkeypatch.setattr(ECMDetector, "ipv4", lambda _: "192.0.2.2")
    probe = WiFiProbe()
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b"Login")
    )
    assert not probe.online("en0")

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("curl", 5)

    monkeypatch.setattr("subprocess.run", timeout)
    assert not probe.online("en0")
