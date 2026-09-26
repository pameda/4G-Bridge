from dataclasses import replace

import pytest

from fourg_bridge.models import DataState, DeviceDescriptor, DeviceState, ModemSnapshot
from fourg_bridge.support.status_item import status_item_style

CONNECTED = ModemSnapshot(
    descriptor=DeviceDescriptor(0x2C7C, 0x0125), device_state=DeviceState.CONNECTED
)


@pytest.mark.parametrize(
    "rssi,level", [(None, 0), (-120, 0), (-105, 0.25), (-95, 0.5), (-85, 0.75), (-75, 1)]
)
def test_cellular_symbol_uses_measured_signal(rssi, level):
    style = status_item_style(replace(CONNECTED, rssi_dbm=rssi))
    assert style.symbol == "cellularbars"
    assert style.level == level and style.secondary
    assert "Wi-Fi" in style.description
    active = status_item_style(replace(CONNECTED, rssi_dbm=rssi, data_state=DataState.ON))
    assert active.level == level and not active.secondary


def test_disconnected_transition_and_error_icons():
    assert status_item_style(ModemSnapshot()).symbol == "cable.connector"
    for state in (DataState.ENABLING, DataState.DISABLING):
        assert (
            status_item_style(replace(CONNECTED, data_state=state)).symbol
            == "arrow.triangle.2.circlepath"
        )
    # Protection warnings must remain visible even after USB disappears.
    assert (
        status_item_style(ModemSnapshot(data_state=DataState.PROTECTION_FAILED)).symbol
        == "exclamationmark.triangle"
    )
    assert (
        status_item_style(replace(CONNECTED, device_state=DeviceState.ERROR)).symbol
        == "exclamationmark.triangle"
    )
