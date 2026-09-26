import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fourg_bridge.app.controller import ApplicationController
from fourg_bridge.app.runtime import ModemRuntime
from fourg_bridge.models import DeviceDescriptor, ModemSnapshot, RegistrationState, SIMState
from fourg_bridge.modem.controller import ModemController
from fourg_bridge.storage.auto_query import AutoQueryLedger, matches_profile, valid_profile
from fourg_bridge.storage.identity import IdentityStore
from fourg_bridge.storage.scoped_budget import ScopedCarrierBudget
from fourg_bridge.storage.settings import Settings, SettingsStore


def snapshot():
    return ModemSnapshot(
        descriptor=DeviceDescriptor(0x2C7C, 0x0125),
        sim_state=SIMState.READY,
        iccid="8" * 20,
        operator="CHN-CT",
        registration=RegistrationState.REGISTERED_HOME,
    )


def test_auto_query_default_off_and_profile_validation(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    assert not store.load().auto_query_enabled
    profile = Settings(auto_query_enabled=True, auto_query_operator="CHN-CT")
    store.save(profile)
    assert store.load() == profile
    store.save(replace(profile, auto_query_command=""))
    assert not store.load().auto_query_enabled
    for operator, number, command in [
        ("", "10001", "108"),
        ("x\n", "10001", "108"),
        ("x", "12345", "108"),
        ("x", "10001", None),
    ]:
        assert not valid_profile(operator, number, command)
    assert not valid_profile(123, "10001", "108")


@pytest.mark.parametrize(
    "change",
    [
        {"descriptor": None},
        {"iccid": None},
        {"sim_state": SIMState.NOT_READY},
        {"registration": RegistrationState.REGISTERED_ROAMING},
        {"operator": "OTHER"},
    ],
)
def test_only_confirmed_home_operator_is_eligible(change):
    assert matches_profile(snapshot(), "CHN-CT")
    assert not matches_profile(replace(snapshot(), **change), "CHN-CT")


def test_reservation_survives_restart_replug_and_time(tmp_path):
    path = tmp_path / "queries.sqlite"
    assert AutoQueryLedger(path).claim("a" * 64, 100000)
    assert not AutoQueryLedger(path).claim("a" * 64, 900000)
    assert AutoQueryLedger(path).claim("b" * 64, 900000)
    assert AutoQueryLedger(path).claim("a" * 64, 900001)
    assert not AutoQueryLedger(path).claim("b" * 64, 900002)
    assert not AutoQueryLedger(path).claim("b" * 64, 1000000)  # No timer retry.


def test_global_limit_and_clock_rollback(tmp_path):
    ledger = AutoQueryLedger(tmp_path / "queries.sqlite")
    for char in "abc":
        assert ledger.claim(char * 64, 100000)
    assert not ledger.claim("d" * 64, 100001)
    assert not ledger.claim("e" * 64, 100)
    assert ledger.claim("f" * 64, 200000)


def test_concurrent_reservations_allow_one_submission(tmp_path):
    ledger = AutoQueryLedger(tmp_path / "queries.sqlite")
    with ThreadPoolExecutor(4) as pool:
        assert sum(pool.map(lambda _: ledger.claim("a" * 64, 100000), range(12))) == 1


@pytest.mark.parametrize("key,now", [("raw-sim", 100000), ("a" * 64, float("nan")), ("a" * 64, 0)])
def test_bad_reservations_rejected(tmp_path, key, now):
    ledger = AutoQueryLedger(tmp_path / "queries.sqlite")
    with pytest.raises(ValueError):
        ledger.claim(key, now)


@pytest.mark.parametrize("damage", ["corrupt", "future", "missing_table"])
def test_query_ledger_damage_is_not_reset(tmp_path, damage):
    path = tmp_path / "queries.sqlite"
    AutoQueryLedger(path).claim("a" * 64, 100000)
    if damage == "corrupt":
        path.write_bytes(b"not a database")
    else:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA user_version=99" if damage == "future" else "DROP TABLE attempts")
    before = path.read_bytes()
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        AutoQueryLedger(path)
    assert path.read_bytes() == before


def test_ready_state_binds_real_snapshot_and_requests_safe_off(tmp_path):
    app = ApplicationController.__new__(ApplicationController)
    app._auto_data = SimpleNamespace(carrier_budget=ScopedCarrierBudget(tmp_path))
    app._runtime = SimpleNamespace(cancel_pending_enable=Mock())
    app._snapshot = ModemSnapshot()
    app._data_busy = False
    app._event = Mock()
    app._start_data_change = Mock()
    app._apply_snapshot(snapshot())
    assert app._auto_data.carrier_budget.key == IdentityStore(tmp_path).sim("8" * 20)
    assert app._auto_data.carrier_budget.status().state == "unknown"
    app._start_data_change.assert_called_once_with(False)
    assert ModemController._sim_state(("+CPIN: NOT READY",)) == SIMState.NOT_READY


def fake_runtime(tmp_path):
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._carrier_deadline = 0
    runtime._database = SimpleNamespace(path=tmp_path / "relay.sqlite")
    runtime._session = SimpleNamespace(transport=SimpleNamespace(transaction=nullcontext))
    runtime._controller = SimpleNamespace(snapshot=snapshot)
    key = IdentityStore(tmp_path).sim("8" * 20)
    runtime._receiver = SimpleNamespace(read_identity=lambda: None, sim_key=key)
    runtime._submit_carrier_query = Mock(return_value="accepted")
    return runtime, key


@pytest.mark.parametrize("change", ["sim", "operator", "late_sim", "consent", "not_ready"])
def test_runtime_rechecks_before_sending(tmp_path, change):
    runtime, key = fake_runtime(tmp_path)
    operator = "CHN-CT"
    if change == "sim":
        runtime._controller.snapshot = lambda: replace(snapshot(), iccid="7" * 20)
    if change == "operator":
        operator = "OTHER"
    if change == "late_sim":
        runtime._receiver.sim_key = None
    if change == "not_ready":
        operator = None
        runtime._controller.snapshot = lambda: replace(snapshot(), sim_state=SIMState.NOT_READY)
    runtime.query_carrier(
        "10001", "108", expected_sim=key, operator=operator, authorized=lambda: change != "consent"
    )
    runtime._submit_carrier_query.assert_not_called()


def test_runtime_accepted_query_bound_to_verified_sim(tmp_path):
    runtime, key = fake_runtime(tmp_path)
    assert (
        runtime.query_carrier(
            "10001", "108", expected_sim=key, operator="CHN-CT", authorized=lambda: True
        )
        == "accepted"
    )
    assert runtime._carrier_query_sim == key
    runtime._submit_carrier_query.assert_called_once_with("10001", "108")


def fake_app(tmp_path, monkeypatch):
    app = ApplicationController.__new__(ApplicationController)
    app._settings = Settings(auto_query_enabled=True, auto_query_operator="CHN-CT")
    app.diagnostic_mode = False
    app._auto_query_seen = None
    app._query_epoch = 0
    app._query_suspended = False
    app._auto_query_ledger = AutoQueryLedger(tmp_path / "auto-query.sqlite")
    app._carrier_busy = app._data_busy = False
    app._runtime_lock = threading.RLock()
    app._auto_data = SimpleNamespace(carrier_budget=SimpleNamespace(key="a" * 64))
    app._runtime = SimpleNamespace(
        carrier_pending=False, query_carrier=Mock(return_value="accepted")
    )
    app._event = Mock()
    app._settings_window = SimpleNamespace(refresh=Mock())
    app.rescan = Mock()
    app._snapshot = snapshot()
    app._settings_store = SettingsStore(tmp_path / "settings.json")
    app._show_alert = Mock()
    monkeypatch.setattr("fourg_bridge.app.controller.AppHelper.callAfter", lambda fn, *a: fn(*a))
    monkeypatch.setattr(
        "fourg_bridge.app.controller.threading.Thread",
        lambda target, **_: SimpleNamespace(start=target),
    )
    return app


@pytest.mark.parametrize("confirmed", [True, False])
def test_enabling_requires_explicit_consent(tmp_path, monkeypatch, confirmed):
    import AppKit

    app = fake_app(tmp_path, monkeypatch)
    app._settings = Settings()
    app._maybe_auto_query = Mock()
    alert = Mock()
    alert.runModal.return_value = (
        AppKit.NSAlertFirstButtonReturn if confirmed else AppKit.NSAlertSecondButtonReturn
    )
    monkeypatch.setattr("fourg_bridge.app.controller.AppKit.NSAlert", Mock())
    AppKit.NSAlert.alloc.return_value.init.return_value = alert
    app.set_auto_query(True, "10001", "108")
    assert app._settings.auto_query_enabled == confirmed
    assert app._settings_store.load().auto_query_enabled == confirmed
    assert app._maybe_auto_query.call_count == int(confirmed)


def test_save_error_never_grants_new_consent(tmp_path, monkeypatch):
    app = fake_app(tmp_path, monkeypatch)
    app._settings_store.save = Mock(side_effect=OSError)
    assert not app._save_query_settings(app._settings)
    app._show_alert.assert_called_once()
    app.set_auto_query(False, "10001", "108")
    assert not app._settings.auto_query_enabled
    assert app._query_epoch == 1


def test_cancellation_while_queued_never_submits(tmp_path, monkeypatch):
    app = fake_app(tmp_path, monkeypatch)
    queued = []
    monkeypatch.setattr(
        "fourg_bridge.app.controller.threading.Thread",
        lambda target, **_: SimpleNamespace(start=lambda: queued.append(target)),
    )
    app._maybe_auto_query(snapshot())
    app._query_epoch += 1  # Disable/re-enable or sleep invalidates the queued attempt.
    queued.pop()()
    app._runtime.query_carrier.assert_not_called()


def test_failed_submit_not_retried_after_restart(tmp_path, monkeypatch):
    app = fake_app(tmp_path, monkeypatch)
    app._runtime.query_carrier.side_effect = OSError
    app._maybe_auto_query(snapshot())
    app = fake_app(tmp_path, monkeypatch)
    app._maybe_auto_query(snapshot())
    app._runtime.query_carrier.assert_not_called()


@pytest.mark.parametrize("same_sim", [True, False])
def test_reply_poll_identity_change_resets_only_old_query(same_sim):
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._receiver = SimpleNamespace(poll=lambda: (), identity="new", sim_key="b")
    runtime._sms_identity = ("old", "a")
    runtime._carrier_query_sim = "b" if same_sim else "a"
    runtime._carrier_deadline = 500
    runtime._carrier_requested_at = object()
    runtime._carrier_number = "10001"
    runtime._carrier_cache_at = object()
    runtime.poll_sms(relay_enabled=False)
    assert runtime._carrier_deadline == (500 if same_sim else 0)
    assert runtime._carrier_cache_at is None
    assert runtime.carrier_sim_key is None


def test_controller_once_per_change_and_restart(tmp_path, monkeypatch):
    app = fake_app(tmp_path, monkeypatch)
    app._maybe_auto_query(snapshot())
    app._maybe_auto_query(snapshot())
    app._runtime.query_carrier.assert_called_once()
    app = fake_app(tmp_path, monkeypatch)
    app._maybe_auto_query(snapshot())
    app._runtime.query_carrier.assert_not_called()


@pytest.mark.parametrize(
    "mode", ["disabled", "diagnostic", "missing_ledger", "mismatch", "pending"]
)
def test_controller_does_not_send_without_valid_conditions(tmp_path, monkeypatch, mode):
    app = fake_app(tmp_path, monkeypatch)
    current = snapshot()
    if mode == "disabled":
        app._settings = Settings()
    if mode == "diagnostic":
        app.diagnostic_mode = True
    if mode == "missing_ledger":
        app._auto_query_ledger = None
    if mode == "mismatch":
        current = replace(current, operator="OTHER")
    if mode == "pending":
        app._runtime.carrier_pending = True
    app._maybe_auto_query(current)
    app._runtime.query_carrier.assert_not_called()
