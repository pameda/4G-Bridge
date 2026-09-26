import pytest

from fourg_bridge.support.event_log import EVENTS, EventLog


def test_bounded_catalogued_chinese_events():
    log = EventLog(limit=2)
    log.add("start")
    log.add("missing")
    log.add("connected")
    assert "应用已启动" not in log.text()
    assert "已检测到" in log.text()
    assert "已检测到" not in log.text(True)
    assert "模块未连接" in log.text(True)
    log.clear()
    assert log.text() == ""


def test_arbitrary_private_strings_cannot_be_logged():
    log = EventLog()
    with pytest.raises(KeyError):
        log.add("private payload")
    assert log.text() == ""
    for code in EVENTS:
        log.add(code)
    assert "private payload" not in log.text()
