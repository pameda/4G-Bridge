"""Bounded Wi-Fi-only probes; never infer Internet availability from an IP."""

from __future__ import annotations

import subprocess

from fourg_bridge.network.ecm import ECMDetector, parse_hardware_ports


class WiFiProbe:
    ENDPOINTS = (
        ("https://captive.apple.com/hotspot-detect.html", b"<BODY>Success</BODY>"),
        ("https://www.msftconnecttest.com/connecttest.txt", b"Microsoft Connect Test"),
    )

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
                        url,
                    ],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0 and expected in result.stdout:
                    return True
            except (OSError, subprocess.SubprocessError):
                continue
        return False
