from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NetworkInterface:
    hardware_port: str
    device: str
    ethernet_address: str | None = None
    service: str | None = None


def parse_hardware_ports(output: str) -> tuple[NetworkInterface, ...]:
    blocks = re.split(r"\n\s*\n", output.strip())
    result: list[NetworkInterface] = []
    for block in blocks:
        values: dict[str, str] = {}
        for line in block.splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                values[key.strip()] = value.strip()
        if "Hardware Port" in values and "Device" in values:
            result.append(
                NetworkInterface(
                    hardware_port=values["Hardware Port"],
                    device=values["Device"],
                    ethernet_address=values.get("Ethernet Address"),
                )
            )
    return tuple(result)


def parse_service_order(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current: str | None = None
    for line in output.splitlines():
        match = re.match(r"\(\d+\)\s+(.+)$", line.strip())
        if match:
            current = match.group(1).lstrip("*").strip()
            continue
        device = re.search(r"Device:\s*([^\s,)]+)", line)
        if current and device:
            result[device.group(1)] = current
    return result


def parse_ordered_services(output: str) -> tuple[tuple[str, str | None], ...]:
    result: list[tuple[str, str | None]] = []
    current_name: str | None = None
    for line in output.splitlines():
        match = re.match(r"\(\d+\)\s+(.+)$", line.strip())
        if match:
            current_name = match.group(1).lstrip("*").strip()
            result.append((current_name, None))
            continue
        hardware_port = re.search(r"Hardware Port:\s*([^,)]+)", line)
        if current_name and hardware_port:
            result[-1] = (current_name, hardware_port.group(1).strip())
    return tuple(result)


class ECMDetector:
    SPECIFIC_MODEM_HINTS = ("baiwang", "qdc507", "ec25", "eg25g")
    GENERIC_MODEM_HINTS = ("usb 10/100", "usb ethernet")

    def discover(self) -> NetworkInterface | None:
        ports = parse_hardware_ports(self._run("/usr/sbin/networksetup", "-listallhardwareports"))
        services = parse_service_order(
            self._run("/usr/sbin/networksetup", "-listnetworkserviceorder")
        )
        candidates = tuple(
            (
                port,
                f"{port.hardware_port} {services.get(port.device, '')}".casefold(),
            )
            for port in ports
        )
        for hints in (self.SPECIFIC_MODEM_HINTS, self.GENERIC_MODEM_HINTS):
            for port, haystack in candidates:
                if any(hint in haystack for hint in hints):
                    return NetworkInterface(
                        port.hardware_port,
                        port.device,
                        port.ethernet_address,
                        services.get(port.device),
                    )
        return None

    @staticmethod
    def default_interface() -> str | None:
        output = ECMDetector._run("/sbin/route", "-n", "get", "default", allow_failure=True)
        match = re.search(r"^\s*interface:\s*(\S+)", output, re.MULTILINE)
        return match.group(1) if match else None

    @staticmethod
    def ipv4(interface: str) -> str | None:
        output = ECMDetector._run(
            "/usr/sbin/ipconfig", "getifaddr", interface, allow_failure=True
        ).strip()
        return output or None

    @staticmethod
    def gateway(interface: str) -> str | None:
        packet = ECMDetector._run("/usr/sbin/ipconfig", "getpacket", interface, allow_failure=True)
        match = re.search(
            r"router_identifier[^:]*:\s*(?:\{\s*)?(\d{1,3}(?:\.\d{1,3}){3})",
            packet,
        )
        if match:
            return match.group(1)
        route = ECMDetector._run("/sbin/route", "-n", "get", "default", allow_failure=True)
        route_interface = re.search(r"^\s*interface:\s*(\S+)", route, re.MULTILINE)
        route_gateway = re.search(r"^\s*gateway:\s*(\S+)", route, re.MULTILINE)
        if route_interface and route_gateway and route_interface.group(1) == interface:
            return route_gateway.group(1)
        return None

    @staticmethod
    def has_vpn() -> bool:
        output = ECMDetector._run("/sbin/ifconfig", allow_failure=True)
        return bool(re.search(r"^utun\d+:.*\n(?:.*\n)*?\s+inet ", output, re.MULTILINE))

    @staticmethod
    def _run(*arguments: str, allow_failure: bool = False) -> str:
        completed = subprocess.run(
            arguments, capture_output=True, text=True, check=False, timeout=5
        )
        if completed.returncode and not allow_failure:
            raise OSError(completed.stderr.strip() or "network command failed")
        return completed.stdout
