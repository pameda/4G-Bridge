from typing import ClassVar

from fourg_bridge.models import (
    ATResponse,
    DeviceDescriptor,
    DeviceState,
    RegistrationState,
    SIMState,
)
from fourg_bridge.modem.controller import ModemController


class Discovery:
    def __init__(self, descriptor=None):
        self.descriptor = descriptor

    def discover(self):
        return self.descriptor


class Transport:
    responses: ClassVar[dict[str, tuple[str, ...]]] = {
        "AT+CPIN?": ("+CPIN: READY",),
        "AT+COPS?": ('+COPS: 0,0,"中国电信",7',),
        "AT+CEREG?": ("+CEREG: 0,1",),
        "AT+QNWINFO": ('+QNWINFO: "FDD LTE","46011","LTE BAND 3",1850',),
        "AT+CSQ": ("+CSQ: 18,99",),
    }

    def transact(self, command):
        return ATResponse(self.responses[command], "OK")


def test_missing_and_descriptor_only() -> None:
    assert ModemController(Discovery()).snapshot().device_state == DeviceState.MISSING
    descriptor = DeviceDescriptor(0x2CA3, 0x4006)
    snapshot = ModemController(Discovery(descriptor)).snapshot()
    assert snapshot.device_state == DeviceState.CONNECTED


def test_full_snapshot() -> None:
    descriptor = DeviceDescriptor(0x2CA3, 0x4006)
    snapshot = ModemController(Discovery(descriptor), Transport()).snapshot()
    assert snapshot.sim_state == SIMState.READY
    assert snapshot.registration == RegistrationState.REGISTERED_HOME
    assert snapshot.operator == "中国电信"
    assert snapshot.rssi_dbm == -77


def test_transport_failure_is_contained() -> None:
    class Failing:
        def transact(self, command):
            raise TimeoutError

    descriptor = DeviceDescriptor(0x2CA3, 0x4006)
    snapshot = ModemController(Discovery(descriptor), Failing()).snapshot()
    assert snapshot.device_state == DeviceState.ERROR
    assert snapshot.warning == "TimeoutError"
