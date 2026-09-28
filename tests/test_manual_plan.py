"""Manual fallback uses synthetic allowances and never touches a real SIM."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from test_auto_query import fake_app

from fourg_bridge.cellular.manual_plan import manual_usage
from fourg_bridge.storage.carrier_budget import CarrierBudgetStore
from fourg_bridge.storage.scoped_budget import ScopedCarrierBudget


@pytest.mark.parametrize(
    "total,left",
    [
        ("", "1"),
        ("NaN", "1"),
        ("Infinity", "1"),
        ("0", "0"),
        ("-1", "0"),
        ("10001", "0"),
        ("10", "11"),
        ("10", "-1"),
        ("10", "NaN"),
        ("10", "abc"),
    ],
)
def test_invalid_manual_quantities(total, left):
    with pytest.raises(ValueError):
        manual_usage(total, left, datetime.now(UTC))


def test_fractional_quantities():
    usage = manual_usage("100", "79.5", datetime.now(UTC))
    assert usage.total_bytes == 100 * 1024**3
    assert usage.used_bytes == int(20.5 * 1024**3)
    assert "手动" in usage.basis


def test_manual_expiry_restart_and_carrier_replacement(tmp_path):
    path = tmp_path / "budget.sqlite"
    now = datetime(2026, 9, 10, tzinfo=UTC)
    store = CarrierBudgetStore(path)
    store.update_plan(manual_usage("100", "90", now), manual=True)
    store = CarrierBudgetStore(path)
    assert store.is_manual()
    assert "手动" in store.usage().basis
    assert store.status(now + timedelta(days=10)).state == "ready"
    assert store.status(now - timedelta(seconds=1)).state == "stale"
    assert store.status(datetime(2026, 10, 1, tzinfo=UTC)).state == "stale"
    store.update_plan(manual_usage("100", "89", now + timedelta(hours=1)))
    assert not store.is_manual()
    assert store.status(now + timedelta(hours=8)).state == "stale"


def test_manual_counters_thresholds_and_same_month_lock(tmp_path):
    store = CarrierBudgetStore(tmp_path / "budget.sqlite")
    now = datetime(2026, 9, 10, tzinfo=UTC)
    store.update_plan(manual_usage("100", "21", now), manual=True)
    store.observe("en11", "boot", 0, 0)
    store.observe("en11", "boot", 1024**3, 0)
    assert store.status(now).state == "confirmation"
    store.approved = True
    assert store.status(now).state == "ready"
    store.observe("en11", "boot", 10 * 1024**3, 9 * 1024**3)
    assert store.status(now).state == "locked"
    store.update_plan(manual_usage("1000", "1000", now + timedelta(seconds=1)), manual=True)
    assert store.status(now + timedelta(seconds=1)).state == "locked"
    new_month = datetime(2026, 10, 1, tzinfo=UTC)
    store.update_plan(manual_usage("100", "100", new_month), manual=True)
    assert store.status(new_month).state == "ready"


def test_manual_bound_to_current_sim(tmp_path):
    store = ScopedCarrierBudget(tmp_path)
    store.bind("8" * 20)
    key = store.key
    usage = manual_usage("100", "90", datetime.now().astimezone())
    store.set_manual_plan(usage, sim_key=key)
    assert store.is_manual()
    store.bind("9" * 20)
    assert store.status().state == "unknown"
    assert not store.is_manual()
    with pytest.raises(ValueError):
        store.set_manual_plan(usage, sim_key=key)
    store.bind("8" * 20)
    assert store.is_manual()
    assert store.status().state == "ready"
    with pytest.raises(ValueError):
        store.set_manual_plan(
            replace(usage, timestamp=usage.timestamp - timedelta(days=1)), sim_key=store.key
        )


@pytest.mark.parametrize("action", ["confirm", "cancel", "swap", "save_error"])
def test_manual_confirmation_does_not_send_sms(tmp_path, monkeypatch, action):
    import AppKit

    app = fake_app(tmp_path, monkeypatch)
    budget = ScopedCarrierBudget(tmp_path / "budget")
    budget.bind("8" * 20)
    app._auto_data.carrier_budget = budget
    app._settings = replace(app._settings, auto_query_enabled=False, auto_data_enabled=False)
    alert = Mock()

    def confirm():
        if action == "swap":
            budget.bind("9" * 20)
        return (
            AppKit.NSAlertSecondButtonReturn
            if action == "cancel"
            else AppKit.NSAlertFirstButtonReturn
        )

    alert.runModal.side_effect = confirm
    monkeypatch.setattr("fourg_bridge.app.controller.AppKit.NSAlert", Mock())
    AppKit.NSAlert.alloc.return_value.init.return_value = alert
    if action == "save_error":
        app._settings_store.save = Mock(side_effect=OSError)
    app.set_manual_carrier_plan("100", "90")
    assert app._settings.auto_data_enabled == (action == "confirm")
    assert not app._settings.auto_query_enabled
    app._runtime.query_carrier.assert_not_called()
    if action in ("cancel", "swap"):
        assert budget.status().state == "unknown"


def test_manual_mode_suppresses_automatic_query(tmp_path, monkeypatch):
    app = fake_app(tmp_path, monkeypatch)
    budget = ScopedCarrierBudget(tmp_path / "budget")
    budget.bind("8" * 20)
    budget.set_manual_plan(
        manual_usage("100", "90", datetime.now().astimezone()), sim_key=budget.key
    )
    app._auto_data.carrier_budget = budget
    app._settings = replace(app._settings, auto_query_detect_carrier=True)
    app._maybe_auto_query(app._snapshot)
    app._runtime.query_carrier.assert_not_called()
    assert "手动套餐" in app._auto_query_status
