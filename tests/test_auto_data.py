from dataclasses import replace
from types import SimpleNamespace

from fourg_bridge.app.auto_data import AutoDataMonitor
from fourg_bridge.app.controller import ApplicationController
from fourg_bridge.models import DataState, ModemSnapshot
from fourg_bridge.network.failover import Action
from fourg_bridge.storage.budget import BudgetStore
from fourg_bridge.storage.settings import Settings


class OneTick:
    def __init__(self):
        self.done = False

    def is_set(self):
        return self.done

    def wait(self, _seconds):
        self.done = True


def monitor(tmp_path, monkeypatch, settings=None):
    settings = settings or Settings(data_limit_bytes=100)
    monkeypatch.setattr(
        "fourg_bridge.app.auto_data.subprocess.run", lambda *a, **kw: SimpleNamespace(stdout="boot")
    )
    calls = []
    snapshot = ModemSnapshot(data_state=DataState.ON, interface="en1", network_service="QDC507")
    controller = SimpleNamespace(
        _settings=settings,
        _settings_store=SimpleNamespace(path=tmp_path / "settings.json"),
        current_snapshot=lambda: snapshot,
        stop_for_budget=lambda: calls.append("off"),
    )
    worker = AutoDataMonitor(controller, BudgetStore(tmp_path / "budget.sqlite"))
    worker.stop = OneTick()
    return worker, calls


def test_guard_turns_off_independently_of_sms_runtime_lock(tmp_path, monkeypatch):
    worker, calls = monitor(tmp_path, monkeypatch)
    worker.budget.observe("en1", "boot", 0, 0, 100)
    sample = SimpleNamespace(interface="en1", rx_bytes=60, tx_bytes=40)
    worker._traffic.sample = lambda _: sample
    worker._guard()
    assert calls == ["off"]
    assert worker.budget.status(100).locked


def test_metering_failure_is_fail_closed(tmp_path, monkeypatch):
    worker, calls = monitor(tmp_path, monkeypatch)

    def broken(_interface):
        raise OSError

    worker._traffic.sample = broken
    worker._guard()
    assert calls == ["off"] and worker.error
    assert not worker.ready()


def test_unconfigured_and_corrupt_accounting_never_auto_enable(tmp_path, monkeypatch):
    worker, calls = monitor(tmp_path, monkeypatch, Settings(auto_data_enabled=True))
    assert not worker.ready()
    worker._guard()
    assert calls == []
    worker.controller._settings = Settings(data_limit_bytes=100)
    worker.budget = None
    assert not worker.ready()


def test_lost_settings_do_not_bypass_persisted_cap(tmp_path, monkeypatch):
    worker, _ = monitor(tmp_path, monkeypatch)
    worker.budget.observe("en1", "boot", 0, 0, 100)
    worker.budget.observe("en1", "boot", 100, 0, 100)
    worker.controller._settings = Settings()
    assert not worker.ready()
    worker.budget = None
    assert not worker.ready()


def test_stale_auto_callback_cannot_enable_after_sleep_or_config_change():
    app = ApplicationController.__new__(ApplicationController)
    app._data_epoch = 4
    app._data_busy = False
    app._settings = Settings(auto_data_enabled=True, data_limit_bytes=100)
    calls = []
    app._auto_data = SimpleNamespace(suspended=False, stop=OneTick(), ready=lambda: True)
    app._start_data_change = lambda *a, **kw: calls.append(a)
    app.auto_data_request(Action.ENABLE, 3)
    assert calls == []
    app._settings = replace(app._settings, auto_data_enabled=False)
    app.auto_data_request(Action.ENABLE, 4)
    assert calls == []
    app._settings = replace(app._settings, auto_data_enabled=True)
    app._auto_data.suspended = True
    app.auto_data_request(Action.ENABLE, 4)
    assert calls == []
    app._auto_data.suspended = False
    app.auto_data_request(Action.ENABLE, 4)
    assert calls == [(True,)]


def test_old_completion_does_not_clear_new_transition_busy_state():
    app = ApplicationController.__new__(ApplicationController)
    app._data_busy = True
    app._data_epoch = 2
    app.rescan = lambda: None
    app._data_finished(None, True, 1)
    assert app._data_busy


def test_menu_can_read_policy_during_controller_initialization():
    app = ApplicationController.__new__(ApplicationController)
    app._settings = Settings(carrier_policy_enabled=True, auto_data_enabled=True)
    settings, used, status = app.data_policy()
    assert settings == app._settings and used == 0
    assert "正在启动" in status


def test_carrier_guard_cuts_at_eighty_before_confirmation(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from fourg_bridge.cellular.carrier_query import CarrierUsage

    worker, calls = monitor(
        tmp_path, monkeypatch, Settings(carrier_policy_enabled=True, auto_data_enabled=True)
    )
    worker.carrier_budget.update_plan(CarrierUsage(1000, 790, datetime.now(UTC)))
    worker.carrier_budget.observe("en1", "boot", 0, 0)
    worker._traffic.sample = lambda _: SimpleNamespace(interface="en1", rx_bytes=5, tx_bytes=5)
    worker._guard()
    assert calls == ["off"]
    assert worker.carrier_budget.status().state == "confirmation"


def test_missing_carrier_data_fails_closed(tmp_path, monkeypatch):
    worker, calls = monitor(
        tmp_path, monkeypatch, Settings(carrier_policy_enabled=True, auto_data_enabled=True)
    )
    worker._traffic.sample = lambda _: SimpleNamespace(interface="en1", rx_bytes=5, tx_bytes=5)
    assert not worker.ready()
    worker._guard()
    assert calls == ["off"]
