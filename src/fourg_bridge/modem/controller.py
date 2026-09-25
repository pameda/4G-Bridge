from __future__ import annotations

import re

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
    _READ_COMMANDS = (
        "ATI",
        'AT+QCFG="usbnet"',
        'AT+QCFG="usbcfg"',
        "AT+CPIN?",
        "AT+QCCID",
        "AT+CNUM",
        "AT+COPS?",
        "AT+CEREG?",
        "AT+CGREG?",
        "AT+CREG?",
        "AT+QNWINFO",
        "AT+CSQ",
    )

    def __init__(self, discovery: USBDiscovery, transport: ATTransport | None = None) -> None:
        self._discovery = discovery
        self._transport = transport

    def snapshot(self) -> ModemSnapshot:
        descriptor = self._discovery.discover()
        if descriptor is None:
            return ModemSnapshot(device_state=DeviceState.MISSING)
        if self._transport is None:
            return ModemSnapshot(device_state=DeviceState.CONNECTED, descriptor=descriptor)
        responses: dict[str, tuple[str, ...]] = {}
        failures: list[str] = []
        for command in self._READ_COMMANDS:
            try:
                response = self._transport.transact(command)
                if response.ok:
                    responses[command] = response.lines
                else:
                    failures.append(response.final.split(":", 1)[0])
            except Exception as error:
                failures.append(type(error).__name__)
        if not responses:
            return ModemSnapshot(
                device_state=DeviceState.ERROR,
                descriptor=descriptor,
                warning=failures[0] if failures else "AT read failed",
            )
        registration = next(
            (
                value
                for command in ("AT+CEREG?", "AT+CGREG?", "AT+CREG?")
                if (value := parse_registration(responses.get(command, ()))) is not None
            ),
            None,
        )
        csq, rssi = parse_csq(responses.get("AT+CSQ", ()))
        return ModemSnapshot(
            device_state=DeviceState.CONNECTED,
            descriptor=descriptor,
            modem_identity=self._identity(responses.get("ATI", ())),
            usb_configuration=self._usb_configuration(responses),
            sim_state=self._sim_state(responses.get("AT+CPIN?", ())),
            iccid=self._digits_value(responses.get("AT+QCCID", ()), "+QCCID:"),
            phone_number=self._phone_value(responses.get("AT+CNUM", ())),
            operator=self._quoted_value(responses.get("AT+COPS?", ()), "+COPS:"),
            registration=self._registration(registration),
            rat=self._quoted_value(responses.get("AT+QNWINFO", ()), "+QNWINFO:"),
            csq=csq,
            rssi_dbm=rssi,
            warning="partial AT read" if failures else None,
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

    @staticmethod
    def _identity(lines: tuple[str, ...]) -> str | None:
        values = [line.strip() for line in lines if line.strip() and line.strip() != "ATI"]
        return " · ".join(values[:3]) or None

    @staticmethod
    def _usb_configuration(responses: dict[str, tuple[str, ...]]) -> str | None:
        values = [
            line.strip()
            for command in ('AT+QCFG="usbnet"', 'AT+QCFG="usbcfg"')
            for line in responses.get(command, ())
            if line.startswith("+QCFG:")
        ]
        return " · ".join(values) or None

    @staticmethod
    def _digits_value(lines: tuple[str, ...], prefix: str) -> str | None:
        for line in lines:
            if line.startswith(prefix):
                digits = "".join(character for character in line if character.isdigit())
                return digits or None
        return None

    @staticmethod
    def _phone_value(lines: tuple[str, ...]) -> str | None:
        for line in lines:
            if line.startswith("+CNUM:"):
                candidates = re.findall(r"\+?\d{5,}", line)
                return max(candidates, key=len) if candidates else None
        return None
