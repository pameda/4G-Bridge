import queue

import pytest

from fourg_bridge.models import DeviceDescriptor
from fourg_bridge.modem.usb_discovery import SUPPORTED_IDS, BulkEndpoints, USBDiscovery
from fourg_bridge.modem.usb_session import USBSessionError, USBSessionFactory


class Endpoint:
    def __init__(self, address, attributes=2):
        self.bEndpointAddress = address
        self.bmAttributes = attributes


class Interface(list):
    bInterfaceNumber = 3


class Device(list):
    manufacturer = "Baiwang"
    product = "QDC507"


class Core:
    def __init__(self, device):
        self.device = device

    def find(self, **kwargs):
        identifier = (kwargs["idVendor"], kwargs["idProduct"])
        return self.device if identifier == SUPPORTED_IDS[0] else None


def test_discovery_and_dynamic_endpoint_scan() -> None:
    device = Device([[Interface([Endpoint(0x04), Endpoint(0x86)])]])
    discovery = USBDiscovery(Core(device))
    descriptor = discovery.discover()
    assert descriptor is not None and descriptor.product_id == 0x4006
    endpoints = discovery.scan_bulk_endpoints(device)
    assert endpoints[0].out_address == 0x04
    assert endpoints[0].in_address == 0x86


def test_session_factory_probes_and_closes(monkeypatch) -> None:
    class USBDevice:
        def __init__(self):
            self.responses = queue.Queue()
            self.responses.put(b"\r\nOK\r\n")
            self.writes = []

        def get_active_configuration(self):
            return None

        def set_configuration(self):
            raise AssertionError("Must not reset the ECM configuration")

        def write(self, endpoint, data, timeout):
            self.writes.append((endpoint, bytes(data)))

        def read(self, endpoint, size, timeout):
            try:
                return self.responses.get_nowait()
            except queue.Empty as error:
                raise TimeoutError from error

    device = USBDevice()

    class Discovery:
        def open_device(self, descriptor):
            return device

        def scan_bulk_endpoints(self, target):
            return (BulkEndpoints(3, 0x04, 0x86),)

    monkeypatch.setattr("usb.util.claim_interface", lambda *args: None)
    monkeypatch.setattr("usb.util.release_interface", lambda *args: None)
    monkeypatch.setattr("usb.util.dispose_resources", lambda *args: None)
    session = USBSessionFactory(Discovery()).connect(DeviceDescriptor(0x2CA3, 0x4006))
    assert device.writes == [(0x04, b"AT\r")]
    session.close()


def test_session_factory_rejects_missing_endpoints() -> None:
    class ConfiguredDevice:
        def get_active_configuration(self):
            return object()

    class Discovery:
        def open_device(self, descriptor):
            return ConfiguredDevice()

        def scan_bulk_endpoints(self, target):
            return ()

    with pytest.raises(USBSessionError):
        USBSessionFactory(Discovery()).connect(DeviceDescriptor(0x2CA3, 0x4006))


def test_at_probe_excludes_ecm_data_interface() -> None:
    ecm = Interface([Endpoint(0x01), Endpoint(0x81)])
    ecm.bInterfaceClass = 0x0A
    serial = Interface([Endpoint(0x04), Endpoint(0x86)])
    serial.bInterfaceClass = 0xFF
    assert USBDiscovery.scan_bulk_endpoints(Device([[ecm, serial]])) == (
        BulkEndpoints(3, 0x04, 0x86),
    )
