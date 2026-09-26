"""Bounded Wi-Fi-only probes; never infer Internet availability from an IP."""

from __future__ import annotations

import json
import re
import subprocess
import time
from ipaddress import ip_address
from urllib.parse import urlparse

from fourg_bridge.network.ecm import ECMDetector, parse_hardware_ports


class WiFiProbe:
    ENDPOINTS = (
        ("https://captive.apple.com/hotspot-detect.html", b"<BODY>Success</BODY>"),
        ("https://www.msftconnecttest.com/connecttest.txt", b"Microsoft Connect Test"),
    )

    def __init__(self) -> None:
        self._resolved: dict[tuple[str, str], tuple[float, str]] = {}

    def interface(self) -> str | None:
        ports = parse_hardware_ports(
            ECMDetector._run("/usr/sbin/networksetup", "-listallhardwareports")
        )
        return next((p.device for p in ports if p.hardware_port.casefold() == "wi-fi"), None)

    def online(self, interface: str | None) -> bool:
        if not interface or not ECMDetector.ipv4(interface):
            return False
        for url, expected in self.ENDPOINTS:
            try:
                host = urlparse(url).hostname or ""
                cached = self._resolved.get((interface, host))
                resolve = (
                    ["--resolve", f"{host}:443:{cached[1]}"]
                    if cached and cached[0] > time.monotonic()
                    else []
                )
                arguments = [
                    "/usr/bin/curl",
                    "-q",
                    "--silent",
                    "--fail",
                    "--noproxy",
                    "*",
                    "--interface",
                    f"if!{interface}",
                    "--connect-timeout",
                    "2",
                    "--max-time",
                    "4",
                    "--max-filesize",
                    "4096",
                    "--proto",
                    "=https",
                ]
                result = subprocess.run(
                    arguments + resolve + [url],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0 and expected in result.stdout:
                    return True
                address = self._resolve_probe(interface, host)
                if address:
                    result = subprocess.run(
                        [*arguments, "--resolve", f"{host}:443:{address}", url],
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                    if result.returncode == 0 and expected in result.stdout:
                        return True
            except (OSError, subprocess.SubprocessError):
                continue
        return False

    def _resolve_probe(self, interface: str, host: str) -> str | None:
        # Per-request resolution for fixed public probe hosts only. Never change
        # system DNS or use DoH's independent transport (which may ignore binding).
        result = subprocess.run(
            [
                "/usr/bin/curl",
                "-q",
                "--silent",
                "--fail",
                "--noproxy",
                "*",
                "--interface",
                f"if!{interface}",
                "--connect-timeout",
                "2",
                "--max-time",
                "4",
                "--max-filesize",
                "4096",
                "--proto",
                "=https",
                "--resolve",
                "dns.alidns.com:443:223.5.5.5",
                f"https://dns.alidns.com/resolve?name={host}&type=A",
            ],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode:
            return None
        try:
            payload = json.loads(result.stdout)
            if payload.get("Status") != 0:
                return None
            for item in payload.get("Answer", []):
                if item.get("type") == 1 and ip_address(item["data"]).is_global:
                    address = str(item["data"])
                    self._resolved[(interface, host)] = (
                        time.monotonic() + min(60, max(1, int(item.get("TTL", 30)))),
                        address,
                    )
                    return address
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
        return None

    def disconnected(self, interface: str | None) -> bool:
        if not interface:
            return True
        output = ECMDetector._run("/sbin/ifconfig", interface)
        # Retained DHCP addresses must not hide a powered-off/disassociated radio.
        return bool(re.search(r"^\s*status:\s*inactive\s*$", output, re.M))
