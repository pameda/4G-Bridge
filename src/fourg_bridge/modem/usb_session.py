from __future__ import annotations

from contextlib import suppress
from typing import Any

import usb.util  # type: ignore[import-untyped]

from fourg_bridge.models import DeviceDescriptor
from fourg_bridge.modem.at_transport import ATTransport
from fourg_bridge.modem.usb_discovery import BulkEndpoints, USBDiscovery


class USBSessionError(RuntimeError):
    pass


class USBModemSession:
    def __init__(
        self,
        device: Any,
        endpoints: BulkEndpoints,
        transport: ATTransport,
    ) -> None:
        self.device = device
        self.endpoints = endpoints
        self.transport = transport

    def close(self) -> None:
        self.transport.close()
        try:
            usb.util.release_interface(self.device, self.endpoints.interface_number)
            usb.util.dispose_resources(self.device)
        except Exception:
            pass


class USBSessionFactory:
    """Re-enumerates and probes all bulk pairs on every physical connection."""

    def __init__(self, discovery: USBDiscovery) -> None:
        self._discovery = discovery

    def connect(self, descriptor: DeviceDescriptor) -> USBModemSession:
        device = self._discovery.open_device(descriptor)
        # SET_CONFIGURATION resets every function of this composite device,
        # including the ECM function owned by macOS. Never reset a live device.
        device.get_active_configuration()
        endpoints = self._discovery.scan_bulk_endpoints(device)
        errors: list[str] = []
        for pair in endpoints:
            session = self._try_pair(device, pair)
            if session is not None:
                return session
            errors.append(f"if{pair.interface_number}:no_at_response")
        raise USBSessionError(",".join(errors) if errors else "no bulk endpoint pairs")

    @staticmethod
    def _try_pair(device: Any, pair: BulkEndpoints) -> USBModemSession | None:
        transport: ATTransport | None = None
        try:
            usb.util.claim_interface(device, pair.interface_number)

            def write(data: bytes, timeout: int) -> object:
                return device.write(pair.out_address, data, timeout=timeout)

            def read(timeout: int) -> bytes:
                try:
                    return bytes(device.read(pair.in_address, 4096, timeout=timeout))
                except Exception as error:
                    if type(error).__name__ in ("USBTimeoutError", "TimeoutError"):
                        raise TimeoutError from error
                    raise

            transport = ATTransport(write, read)
            if transport.transact("AT", timeout=1.5).ok:
                return USBModemSession(device, pair, transport)
            transport.close()
        except Exception:
            if transport is not None:
                transport.close()
        with suppress(Exception):
            usb.util.release_interface(device, pair.interface_number)
        return None
