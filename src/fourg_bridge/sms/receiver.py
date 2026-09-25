from __future__ import annotations

import re

from fourg_bridge.models import RawSMSPart
from fourg_bridge.modem.at_transport import ATTransport

_CMGL_RE = re.compile(r'^\+CMGL:\s*(\d+),[^,]*(?:,"[^"]*")*,?(\d+)?')


class SMSReceiver:
    def __init__(self, transport: ATTransport, stores: tuple[str, ...] = ("ME", "SM")) -> None:
        self._transport = transport
        self._stores = stores

    def poll(self) -> tuple[RawSMSPart, ...]:
        parts: list[RawSMSPart] = []
        self._transport.transact("AT+CMGF=0")
        for storage in self._stores:
            selected = self._transport.transact(f'AT+CPMS="{storage}"')
            if not selected.ok:
                continue
            response = self._transport.transact("AT+CMGL=4", timeout=15)
            parts.extend(self._parse_listing(storage, response.lines))
        return tuple(parts)

    @staticmethod
    def _parse_listing(storage: str, lines: tuple[str, ...]) -> tuple[RawSMSPart, ...]:
        result: list[RawSMSPart] = []
        index = 0
        while index < len(lines):
            match = _CMGL_RE.match(lines[index])
            if match and index + 1 < len(lines):
                pdu = lines[index + 1].strip()
                if pdu and all(ch in "0123456789ABCDEFabcdef" for ch in pdu):
                    result.append(RawSMSPart(storage, int(match.group(1)), pdu))
                index += 2
            else:
                index += 1
        return tuple(result)

    def delete(self, locations: tuple[tuple[str, int], ...]) -> bool:
        for storage, index in locations:
            if not self._transport.transact(f'AT+CPMS="{storage}"').ok:
                return False
            if not self._transport.transact(f"AT+CMGD={index}").ok:
                return False
        return True
