from __future__ import annotations

from fourg_bridge.models import (
    DeviceState,
    ModemSnapshot,
    RegistrationState,
    SIMState,
)
from fourg_bridge.modem.at_parser import parse_csq, parse_registration
from fourg_bridge.modem.at_transport import ATTransport
from fourg_bridge.modem.usb_discovery import USBDiscovery


class ModemController:
    def __init__(self, discovery: USBDiscovery, transport: ATTransport | None = None) -> None:
        self._discovery = discovery
        self._transport = transport

    def snapshot(self) -> ModemSnapshot:
        descriptor = self._discovery.discover()
        if descriptor is None:
            return ModemSnapshot(device_state=DeviceState.MISSING)
        if self._transport is None:
            return ModemSnapshot(device_state=DeviceState.CONNECTED, descriptor=descriptor)
        try:
            cpin = self._transport.transact("AT+CPIN?")
            cops = self._transport.transact("AT+COPS?")
            cereg = self._transport.transact("AT+CEREG?")
            qnwinfo = self._transport.transact("AT+QNWINFO")
            csq_response = self._transport.transact("AT+CSQ")
        except Exception as error:
            return ModemSnapshot(
                device_state=DeviceState.ERROR,
                descriptor=descriptor,
                warning=type(error).__name__,
            )
        csq, rssi = parse_csq(csq_response.lines)
        return ModemSnapshot(
            device_state=DeviceState.CONNECTED,
            descriptor=descriptor,
            sim_state=self._sim_state(cpin.lines),
            operator=self._quoted_value(cops.lines, "+COPS:"),
            registration=self._registration(parse_registration(cereg.lines)),
            rat=self._quoted_value(qnwinfo.lines, "+QNWINFO:"),
            csq=csq,
            rssi_dbm=rssi,
        )

    @staticmethod
    def _sim_state(lines: tuple[str, ...]) -> SIMState:
        joined = " ".join(lines).upper()
        if "READY" in joined:
            return SIMState.READY
        if "SIM PIN" in joined:
            return SIMState.PIN_REQUIRED
        if "NOT INSERTED" in joined:
            return SIMState.MISSING
        return SIMState.NOT_READY

    @staticmethod
    def _registration(value: int | None) -> RegistrationState:
        mapping = {
            0: RegistrationState.NOT_REGISTERED,
            1: RegistrationState.REGISTERED_HOME,
            2: RegistrationState.SEARCHING,
            3: RegistrationState.DENIED,
            5: RegistrationState.REGISTERED_ROAMING,
        }
        return (
            mapping.get(value, RegistrationState.UNKNOWN)
            if value is not None
            else RegistrationState.UNKNOWN
        )

    @staticmethod
    def _quoted_value(lines: tuple[str, ...], prefix: str) -> str | None:
        for line in lines:
            if line.startswith(prefix):
                quoted = line.split('"')
                return quoted[1] if len(quoted) >= 3 else line.split(":", 1)[1].strip()
        return None
