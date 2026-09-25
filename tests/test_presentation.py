from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from fourg_bridge.models import DataState, DeviceDescriptor, ModemSnapshot, TrafficSnapshot
from fourg_bridge.support.presentation import (
    SpeedHistory,
    connection_title,
    format_bytes,
    operator_name,
    route_description,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0 B"),
        (1024, "1.0 KB"),
        (1024**3, "1.0 GB"),
        (1024**5, "1024.0 TB"),
        (-1, "—"),
        (float("nan"), "—"),
    ],
)
def test_format_bytes(value, expected):
    assert format_bytes(value) == expected


def test_connection_display_does_not_claim_internet_or_wifi_underlay():
    absent = ModemSnapshot()
    assert connection_title(absent) == "连接你的 4G 模块"
    connected = replace(absent, descriptor=DeviceDescriptor(0x2C7C, 0x0125))
    assert connection_title(connected) == "4G 已待命"
    assert connection_title(replace(connected, data_state=DataState.ON)) == "4G 数据已开启"
    assert "保护" in connection_title(replace(absent, data_state=DataState.PROTECTION_FAILED))
    assert "处理" in connection_title(replace(connected, warning="timeout"))
    assert route_description(replace(connected, vpn_active=True)).startswith("VPN")
    assert route_description(replace(connected, default_interface="en0")).endswith("en0")
    assert "尚未" in route_description(absent)
    assert operator_name(None) == "等待识别"
    assert operator_name("CHN-CT") == "中国电信"
    assert operator_name("Other") == "Other"


def test_chart_uses_unique_measured_samples_and_resets_on_gaps():
    history = SpeedHistory(capacity=2)
    now = datetime.now().astimezone()
    sample = TrafficSnapshot("en11", now, 0, 0, 100, 50)
    history.add(sample)
    history.add(sample)
    assert len(history.samples) == 1
    assert history.normalized() == (1.0,)
    assert history.normalized(True) == (0.5,)
    history.add(replace(sample, sampled_at=now + timedelta(seconds=5)))
    history.add(replace(sample, sampled_at=now + timedelta(seconds=10)))
    assert len(history.samples) == 2
    history.add(replace(sample, sampled_at=now + timedelta(seconds=50)))
    assert len(history.samples) == 1
    history.add(replace(sample, interface="en12"))
    assert len(history.samples) == 1
    history.add(None)
    assert history.normalized() == ()
    history.add(replace(sample, download_bps=0, upload_bps=0))
    assert history.normalized() == (0.0,)
