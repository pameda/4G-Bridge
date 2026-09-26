"""Recovery from isolated relay testing must not leave USB permanently invisible."""

from types import SimpleNamespace

import pytest

from fourg_bridge.app.controller import ApplicationController
from fourg_bridge.models import DataState, ModemSnapshot
from fourg_bridge.storage.settings import Settings


def controller(calls, *, save_failure=False, relay_enabled=True):
    app = ApplicationController.__new__(ApplicationController)
    app.diagnostic_mode = True
    app._settings = Settings(relay_enabled=relay_enabled)
    app._snapshot = ModemSnapshot()
    app._recent_relay = None

    def save(settings):
        if save_failure:
            raise OSError("disk unavailable")
        assert settings.relay_enabled is relay_enabled
        calls.append("save-preference")

    app._settings_store = SimpleNamespace(save=save)
    app._menu = SimpleNamespace(
        setRelayStatus_recent_=lambda enabled, recent: calls.append(f"relay-{enabled}"),
        update_=lambda snapshot: calls.append("menu"),
    )
    app._settings_window = SimpleNamespace(refresh=lambda *a: calls.append("window"))
    app._auto_data = SimpleNamespace(start=lambda: calls.append("start-quota-guard"))
    app.rescan = lambda: calls.append("scan")
    app._show_alert = lambda *a: calls.append("alert")
    return app


@pytest.mark.parametrize("enabled", [True, False])
def test_resume_preserves_relay_preference_without_enabling_data(enabled):
    calls = []
    app = controller(calls, relay_enabled=enabled)
    assert not app.relay_enabled()
    app.resume_modem_control()
    assert not app.diagnostic_mode
    assert app.relay_enabled() is enabled
    assert app._snapshot.data_state == DataState.OFF
    assert calls == [
        "save-preference",
        f"relay-{enabled}",
        "menu",
        "window",
        "start-quota-guard",
        "scan",
    ]
    app.resume_modem_control()
    assert calls.count("start-quota-guard") == 1


def test_failed_safe_settings_write_keeps_diagnostics_isolated():
    calls = []
    app = controller(calls, save_failure=True)
    app.resume_modem_control()
    assert app.diagnostic_mode
    assert calls == ["alert"]


@pytest.mark.parametrize("action", ["toggle_data", "redetect"])
def test_diagnostic_controls_offer_recovery_instead_of_fake_failure(action):
    app = ApplicationController.__new__(ApplicationController)
    app.diagnostic_mode = True
    calls = []
    app.request_resume_modem_control = lambda: calls.append("offer-recovery")
    getattr(app, action)()
    assert calls == ["offer-recovery"]


def test_internal_data_transition_cannot_bypass_diagnostic_isolation():
    app = ApplicationController.__new__(ApplicationController)
    app.diagnostic_mode = True
    app._start_data_change(True)
    app._start_data_change(False)
