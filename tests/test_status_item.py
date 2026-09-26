from dataclasses import replace

import pytest

from fourg_bridge.models import DataState, DeviceDescriptor, DeviceState, ModemSnapshot
from fourg_bridge.support.status_item import badge_palette, status_item_style

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


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("state", list(DataState))
def test_badge_palette_label_contrast_and_color(dark, state):
    style = status_item_style(replace(CONNECTED, data_state=state))
    palette = badge_palette(style, dark=dark)

    def luminance(rgb):
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    fg, bg = luminance(palette.foreground), luminance(palette.background)
    assert (max(fg, bg) + 0.05) / (min(fg, bg) + 0.05) >= 4.5
    # No solid black badge; warning amber remains distinct from blue connection states.
    assert min(palette.background) > 0
    r, _, b = palette.background
    assert (r > b) == (state == DataState.PROTECTION_FAILED)


def test_offline_and_paused_are_muted_but_have_different_shapes():
    offline = status_item_style(ModemSnapshot())
    paused = status_item_style(CONNECTED)
    assert offline.symbol != paused.symbol
    assert badge_palette(offline, dark=False) == badge_palette(paused, dark=False)
