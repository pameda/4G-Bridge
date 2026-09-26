"""Small, typed boundary around Windows commands; no third-party drivers."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

SUPPORTED = re.compile(r"(?:^|[\\&])(?:VID_2CA3&PID_4006|VID_2C7C&PID_0125)(?=[\\&]|$)", re.I)


def compatible(pnp: str) -> bool:
    return bool(SUPPORTED.search(pnp))


class PlatformError(RuntimeError):
    """Only fixed, public error descriptions escape the platform boundary."""


def system_exe(name: str) -> str:
    root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
    return str(root / name)


def run_ps(script: str, timeout: float = 15) -> Any:
    if sys.platform != "win32":
        raise PlatformError("此操作需要 Windows")
    prefix = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();$ErrorActionPreference='Stop';"
    try:
        result = subprocess.run(
            [
                system_exe(r"WindowsPowerShell\v1.0\powershell.exe"),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                prefix + script,
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=0x08000000,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlatformError("Windows 系统操作超时或不可用") from exc
    if result.returncode:
        raise PlatformError("Windows 系统操作失败，请检查管理员权限及设备驱动")
    try:
        return json.loads(result.stdout.strip().lstrip("\ufeff")) if result.stdout.strip() else None
    except ValueError as exc:
        raise PlatformError("Windows 返回的数据格式不可用") from exc


@dataclass(frozen=True)
class Adapter:
    guid: str
    index: int
    name: str
    pnp: str
    wifi: bool
    physical: bool
    enabled: bool
    connected: bool
    ipv4: str = ""
    gateway: str = ""
    default: bool = False

    @property
    def modem(self) -> bool:
        return compatible(self.pnp)

    @property
    def usable(self) -> bool:
        try:
            address = ipaddress.IPv4Address(self.ipv4)
            return self.connected and not (address.is_link_local or address.is_unspecified)
        except ValueError:
            return False


@dataclass(frozen=True)
class Port:
    name: str
    label: str
    pnp: str


@dataclass(frozen=True)
class Inventory:
    adapters: tuple[Adapter, ...] = ()
    ports: tuple[Port, ...] = ()
    usb_present: bool = False
    boot: str = ""

    def modem(self) -> Adapter | None:
        matches = [item for item in self.adapters if item.modem]
        # Never guess between two modem NICs / two modules.
        return matches[0] if len(matches) == 1 else None


def parse_inventory(data: dict[str, Any]) -> Inventory:
    adapters = []
    for row in data.get("adapters") or []:
        try:
            guid = str(UUID(str(row["guid"]).strip("{}")))
            index = int(row["index"])
            if index <= 0:
                continue
            adapters.append(
                Adapter(
                    guid,
                    index,
                    str(row["name"]),
                    str(row["pnp"]),
                    row.get("wifi") is True,
                    row.get("physical") is True,
                    row.get("enabled") is True,
                    row.get("connected") is True,
                    str(row.get("ipv4") or ""),
                    str(row.get("gateway") or ""),
                    row.get("default") is True,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    ports = tuple(
        Port(str(row["port"]), str(row.get("label", "")), str(row["pnp"]))
        for row in (data.get("ports") or [])
        if compatible(str(row.get("pnp", "")))
        and re.fullmatch(r"COM[1-9][0-9]{0,3}", str(row.get("port", "")))
    )
    return Inventory(tuple(adapters), ports, data.get("present") is True, str(data.get("boot", "")))


# Device identifiers stay in memory. Only counts / fixed statuses enter logs.
INVENTORY_SCRIPT = r"""
$nics=@(Get-CimInstance Win32_NetworkAdapter);
$native=@(Get-NetAdapter -IncludeHidden);
$ips=@(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue);
$routes=@(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue);
$best=$routes | Sort-Object @{Expression={$_.RouteMetric+$_.InterfaceMetric}} |
 Select-Object -First 1;
$adapters=@(foreach($n in $nics) {
 if(!$n.GUID -or !$n.InterfaceIndex){continue};
 $a=$native | Where-Object {$_.ifIndex -eq $n.InterfaceIndex} | Select-Object -First 1;
 $ip=$ips | Where-Object {$_.InterfaceIndex -eq $n.InterfaceIndex -and
 $_.AddressState -eq 'Preferred'} | Select-Object -First 1;
 $r=$routes | Where-Object {$_.InterfaceIndex -eq $n.InterfaceIndex} | Select-Object -First 1;
 [pscustomobject]@{guid=$n.GUID;index=[int]$n.InterfaceIndex;name=$n.NetConnectionID;pnp=$n.PNPDeviceID;
 wifi=($a.NdisPhysicalMedium -eq 9 -or $a.NdisPhysicalMedium -eq 1);
 physical=[bool]$n.PhysicalAdapter;enabled=($n.NetEnabled -eq $true);
 connected=($n.NetConnectionStatus -eq 2);ipv4=$ip.IPAddress;gateway=$r.NextHop;
 default=($null -ne $best -and $best.InterfaceIndex -eq $n.InterfaceIndex)}
});
$ports=@(Get-CimInstance Win32_SerialPort | ForEach-Object {
 [pscustomobject]@{port=$_.DeviceID;label=$_.Name;pnp=$_.PNPDeviceID}
});
$present=@(Get-PnpDevice -PresentOnly | Where-Object {
 $_.InstanceId -match 'VID_2CA3&PID_4006|VID_2C7C&PID_0125'
}).Count -gt 0;
@{adapters=$adapters;ports=$ports;present=$present;
 boot=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
} | ConvertTo-Json -Depth 5 -Compress
"""


def inventory() -> Inventory:
    return parse_inventory(run_ps(INVENTORY_SCRIPT))


def change_adapter(guid: str, enabled: bool) -> None:
    """Revalidate VID/PID immediately before a narrow, privileged mutation."""
    safe_guid = str(UUID(guid))
    action = "Enable-NetAdapter" if enabled else "Disable-NetAdapter"
    script = rf"""
$n=@(Get-CimInstance Win32_NetworkAdapter | Where-Object {{
 $_.GUID -and $_.GUID.Trim('{{}}') -eq '{safe_guid}' -and
 $_.PNPDeviceID -match '(VID_2CA3&PID_4006|VID_2C7C&PID_0125)(&|\\|$)'
}});
if($n.Count -ne 1){{throw 'Target unavailable'}};
$a=Get-NetAdapter -IncludeHidden | Where-Object {{$_.ifIndex -eq $n[0].InterfaceIndex}};
if(@($a).Count -ne 1){{throw 'Adapter unavailable'}};
$a | {action} -Confirm:$false -ErrorAction Stop;
"""
    # Do not change DNS, metrics, default routes, Wi-Fi or VPN. Failover is checked
    # against actual routes; no successful connection is claimed on enable alone.
    run_ps(script, timeout=25)


def adapter_metric(guid: str, metric: int | None = None, automatic: bool = False) -> dict[str, Any]:
    safe_guid = str(UUID(guid))
    if metric is not None and not 1 <= metric <= 9999:
        raise ValueError("invalid metric")
    script = rf"""
$n=@(Get-CimInstance Win32_NetworkAdapter | Where-Object {{
 $_.GUID -and $_.GUID.Trim('{{}}') -eq '{safe_guid}' -and
 $_.PNPDeviceID -match '(VID_2CA3&PID_4006|VID_2C7C&PID_0125)(&|\\|$)'
}});
if($n.Count -ne 1){{throw 'Target unavailable'}};
$ip=Get-NetIPInterface -InterfaceIndex $n[0].InterfaceIndex -AddressFamily IPv4;
"""
    if metric is not None:
        setting = (
            "-AutomaticMetric Enabled"
            if automatic
            else f"-AutomaticMetric Disabled -InterfaceMetric {metric}"
        )
        script += f"$ip | Set-NetIPInterface {setting} -ErrorAction Stop;"
    script += (
        "@{metric=[int]$ip.InterfaceMetric;automatic=($ip.AutomaticMetric -eq 'Enabled')}"
        " | ConvertTo-Json -Compress"
    )
    result = run_ps(script)
    if not isinstance(result, dict):
        raise PlatformError("网卡优先级读取失败")
    return result


def wifi_probe(adapter: Adapter) -> bool:
    if not adapter.wifi or not adapter.usable:
        return False
    ipaddress.IPv4Address(adapter.ipv4)
    from fourg_bridge.windows.probe import online

    return online(adapter.index, adapter.ipv4)
