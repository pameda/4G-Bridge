from __future__ import annotations

import re
import subprocess

from fourg_bridge.modem.at_transport import ATTransport
from fourg_bridge.network.ecm import parse_hardware_ports, parse_ordered_services


class NetworkSetupControl:
    def ensure_wifi_precedes(self, service: str) -> bool:
        completed = subprocess.run(
            ["/usr/sbin/networksetup", "-listnetworkserviceorder"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if completed.returncode:
            return False
        entries = parse_ordered_services(completed.stdout)
        names = [name for name, _port in entries]
        wifi = next(
            (
                name
                for name, port in entries
                if (port or "").casefold() == "wi-fi" or name.casefold() == "wi-fi"
            ),
            None,
        )
        if wifi is None or service not in names:
            return True
        wifi_index = names.index(wifi)
        modem_index = names.index(service)
        if wifi_index < modem_index:
            return True
        names.pop(wifi_index)
        modem_index = names.index(service)
        names.insert(modem_index, wifi)
        reordered = subprocess.run(
            ["/usr/sbin/networksetup", "-ordernetworkservices", *names],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if reordered.returncode:
            return False
        verification = subprocess.run(
            ["/usr/sbin/networksetup", "-listnetworkserviceorder"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        verified_names = [name for name, _port in parse_ordered_services(verification.stdout)]
        return (
            verification.returncode == 0
            and wifi in verified_names
            and service in verified_names
            and verified_names.index(wifi) < verified_names.index(service)
        )

    @staticmethod
    def verify_wifi_default() -> bool:
        ports = subprocess.run(
            ["/usr/sbin/networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if ports.returncode:
            return False
        wifi_device = next(
            (
                item.device
                for item in parse_hardware_ports(ports.stdout)
                if item.hardware_port.casefold() == "wi-fi"
            ),
            None,
        )
        if wifi_device is None:
            return True
        address = subprocess.run(
            ["/usr/sbin/ipconfig", "getifaddr", wifi_device],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if address.returncode or not address.stdout.strip():
            return True
        route = subprocess.run(
            ["/sbin/route", "-n", "get", "default"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        match = re.search(r"^\s*interface:\s*(\S+)", route.stdout, re.MULTILINE)
        if route.returncode or match is None:
            return False
        default_device = match.group(1)
        return default_device == wifi_device or default_device.startswith("utun")

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
