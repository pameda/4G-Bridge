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


class ECMDetector:
    MODEM_HINTS = ("baiwang", "qdc507", "ec25", "usb 10/100", "usb ethernet")

    def discover(self) -> NetworkInterface | None:
        ports = parse_hardware_ports(self._run("/usr/sbin/networksetup", "-listallhardwareports"))
        services = parse_service_order(
            self._run("/usr/sbin/networksetup", "-listnetworkserviceorder")
        )
        for port in ports:
            haystack = f"{port.hardware_port} {services.get(port.device, '')}".casefold()
            if any(hint in haystack for hint in self.MODEM_HINTS):
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
