from __future__ import annotations

import subprocess

from fourg_bridge.modem.at_transport import ATTransport


class NetworkSetupControl:
    def set_enabled(self, service: str, enabled: bool) -> bool:
        state = "on" if enabled else "off"
        completed = subprocess.run(
            ["/usr/sbin/networksetup", "-setnetworkserviceenabled", service, state],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return completed.returncode == 0

    def is_enabled(self, service: str) -> bool:
        completed = subprocess.run(
            ["/usr/sbin/networksetup", "-listallnetworkservices"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if completed.returncode:
            return False
        for line in completed.stdout.splitlines():
            value = line.strip()
            if value.lstrip("*") == service:
                return not value.startswith("*")
        return False


class ModemAttachControl:
    def __init__(self, transport: ATTransport) -> None:
        self._transport = transport

    def set_attached(self, attached: bool) -> bool:
        return self._transport.transact(f"AT+CGATT={1 if attached else 0}", timeout=15).ok
