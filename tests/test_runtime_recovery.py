from types import SimpleNamespace

from fourg_bridge.app.runtime import ModemRuntime
from fourg_bridge.models import ATResponse, DataState, DeviceDescriptor
from fourg_bridge.network.data_session import DataTransition


def test_recovery_is_bounded_and_requires_explicit_enable(monkeypatch):
    calls = []
    failed = DataTransition(DataState.OFF, DataState.OFF, True, "no DHCP", "network_not_ready")
    session = SimpleNamespace(
        transport=SimpleNamespace(
            transact=lambda command, **kw: (calls.append(command) or ATResponse((), "OK"))
        ),
        close=lambda: calls.append("close"),
    )
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._data = SimpleNamespace(set_enabled=lambda *a, **kw: failed)
    runtime._session = session
    runtime._discovery = SimpleNamespace(discover=lambda: DeviceDescriptor(0x2C7C, 0x0125))
    runtime._database = object()
    runtime._bridge = object()
    monkeypatch.setattr("fourg_bridge.app.runtime.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "fourg_bridge.app.runtime.USBSessionFactory",
        lambda _: SimpleNamespace(connect=lambda _: session),
    )
    monkeypatch.setattr("fourg_bridge.app.runtime.SMSRelay", lambda *a: object())

    def bind(self):
        self._data = SimpleNamespace(set_enabled=lambda *a, **kw: failed)

    monkeypatch.setattr(ModemRuntime, "_bind_data_manager", bind)
    assert runtime.set_data(False, False) == failed
    assert runtime.set_data(True, False) == failed
    assert calls == []
    assert runtime.set_data(True, True) == failed
    assert calls.count("AT+CFUN=1,1") == 1
    assert calls.count("close") == 1


def test_unsafe_off_never_reboots_modem():
    failed = DataTransition(
        DataState.OFF, DataState.PROTECTION_FAILED, False, "unsafe", "network_not_ready"
    )
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._data = SimpleNamespace(set_enabled=lambda *a: failed)
    assert runtime.set_data(True, True) == failed


def test_sleep_cancellation_cannot_start_recovery():
    runtime = ModemRuntime.__new__(ModemRuntime)
    safe = DataTransition(DataState.ON, DataState.OFF, True)

    def enable(*args):
        runtime.cancel_pending_enable()
        return DataTransition(DataState.OFF, DataState.OFF, True, "no IP", "network_not_ready")

    runtime._data = SimpleNamespace(set_enabled=enable, force_safe_off=lambda: safe)
    assert runtime.set_data(True, True) == safe
