from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fourg_bridge.models import DeviceDescriptor

SUPPORTED_IDS = ((0x2CA3, 0x4006), (0x2C7C, 0x0125))


class _PackagedUSBCore:
    def __init__(self) -> None:
        import libusb_package
        import usb.core  # type: ignore[import-untyped]

        self._core = usb.core
        self._backend = libusb_package.get_libusb1_backend()

    def find(self, **arguments: Any) -> Any:
        return self._core.find(backend=self._backend, **arguments)


@dataclass(frozen=True, slots=True)
class BulkEndpoints:
    interface_number: int
    out_address: int
    in_address: int


class USBDiscovery:
    def __init__(self, usb_core: Any | None = None) -> None:
        self._usb_core = usb_core

    def discover(self) -> DeviceDescriptor | None:
        core = self._core()
        for vendor_id, product_id in SUPPORTED_IDS:
            device = core.find(idVendor=vendor_id, idProduct=product_id)
            if device is None:
                continue
            return DeviceDescriptor(
                vendor_id=vendor_id,
                product_id=product_id,
                manufacturer=self._safe_string(device, "manufacturer"),
                product=self._safe_string(device, "product"),
                serial_number=None,
            )
        return None

    def open_device(self, descriptor: DeviceDescriptor) -> Any:
        device = self._core().find(idVendor=descriptor.vendor_id, idProduct=descriptor.product_id)
        if device is None:
            raise OSError("QDC507 disappeared during discovery")
        return device

    @staticmethod
    def scan_bulk_endpoints(device: Any) -> tuple[BulkEndpoints, ...]:
        found: list[BulkEndpoints] = []
        for configuration in device:
            for interface in configuration:
                if int(getattr(interface, "bInterfaceClass", 0xFF)) != 0xFF:
                    continue
                out_address: int | None = None
                in_address: int | None = None
                for endpoint in interface:
                    attributes = int(endpoint.bmAttributes) & 0x03
                    if attributes != 0x02:
                        continue
                    address = int(endpoint.bEndpointAddress)
                    if address & 0x80:
                        in_address = address
                    else:
                        out_address = address
                if in_address is not None and out_address is not None:
                    found.append(
                        BulkEndpoints(int(interface.bInterfaceNumber), out_address, in_address)
                    )
        return tuple(found)

    def _core(self) -> Any:
        if self._usb_core is not None:
            return self._usb_core
        self._usb_core = _PackagedUSBCore()
        return self._usb_core

    @staticmethod
    def _safe_string(device: Any, attribute: str) -> str | None:
        try:
            value = getattr(device, attribute, None)
            return str(value) if value else None
        except Exception:
            return None
