from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from fourg_bridge.app.login_item import LoginItem
from fourg_bridge.cellular.carrier_query import parse_allowance, parse_usage, query_pdu, send_query
from fourg_bridge.models import ATResponse


def test_submit_pdu_and_length():
    pdu, length = query_pdu("10001", "108")
    assert pdu == "00010005810100F1000806003100300038"
    assert length == len(bytes.fromhex(pdu)) - 1


@pytest.mark.parametrize(
    "number,command", [("123", "108"), ("10001", ""), ("10001", "108\rAT"), ("10001", "x" * 17)]
)
def test_invalid_query_rejected(number, command):
    with pytest.raises(ValueError):
        query_pdu(number, command)


def test_query_requires_explicit_confirmation():
    with pytest.raises(ValueError):
        send_query(object(), "10001", "108", confirmed=False)


@pytest.mark.parametrize("mode", ["ok", "timeout", "error", "setup_error"])
def test_query_single_attempt_never_retries(mode):
    calls = []

    def transact(command, payload=None, timeout=5):
        calls.append(command)
        if command == "AT+CMGF=0":
            return ATResponse((), "ERROR" if mode == "setup_error" else "OK")
        assert payload and timeout == 30
        if mode == "timeout":
            raise TimeoutError
        return ATResponse(("+CMGS: 1",), "ERROR" if mode == "error" else "OK")

    message = send_query(SimpleNamespace(transact=transact), "10001", "108", confirmed=True)
    assert len(calls) == (1 if mode == "setup_error" else 2)
    assert message
    if mode == "timeout":
        assert "不确定" in message


@pytest.mark.parametrize(
    "body,value",
    [
        ("剩余流量为18GB。", 18 * 1024**3),
        ("国内流量剩余：512MB", 512 * 1024**2),
        ("剩余通用流量 1.5GB", int(1.5 * 1024**3)),
        ("剩余流量 12KB", 12 * 1024),
    ],
)
def test_explicit_allowance_only(body, value):
    result = parse_allowance("10001", body, datetime.now(UTC))
    assert result and result.remaining_bytes == value


@pytest.mark.parametrize(
    "sender,body",
    [
        ("other", "剩余流量18GB"),
        ("10001", "流量已用18GB"),
        ("10001", "剩余流量1GB，剩余流量2GB"),
        ("10001", "欢迎"),
    ],
)
def test_ambiguous_or_noncarrier_not_guessed(sender, body):
    assert parse_allowance(sender, body, datetime.now(UTC)) is None


def test_login_item_uses_system_state_not_saved_boolean():
    class Service:
        value = 0

        def status(self):
            return self.value

        def registerAndReturnError_(self, _error):
            self.value = 2
            return True, None

        def unregisterAndReturnError_(self, _error):
            self.value = 0
            return True, None

    login = LoginItem(Service())
    assert login.status() == 0
    assert login.set_enabled(True) == (True, 2)
    assert login.set_enabled(False) == (True, 0)


@pytest.mark.parametrize("used", ["0", "12", "60"])
def test_carrier_percentage(used):
    usage = parse_usage("10001", f"总流量60GB，已使用{used}GB", datetime.now(UTC))
    assert usage and usage.fraction == int(used) / 60


@pytest.mark.parametrize(
    "body",
    [
        "剩余流量48GB",
        "总流量0GB，已使用0GB",
        "总流量60GB，已使用61GB",
        "总流量60GB，已使用12GB，剩余流量3GB",
        "总流量60GB，已使用12GB，定向流量3GB",
        "总流量60GB，已使用12GB，总流量3GB，已使用1GB",
    ],
)
def test_percentage_unknown_not_invented(body):
    assert parse_usage("10001", body, datetime.now(UTC)) is None


def test_query_reply_parsed_without_relay_or_deletion(monkeypatch):
    from fourg_bridge.app.runtime import ModemRuntime
    from fourg_bridge.models import AssembledSMS

    now = datetime.now(UTC)
    message = AssembledSMS("10001", now, "总流量60GB，已使用12GB，剩余流量48GB", (), ())
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._receiver = SimpleNamespace(poll=lambda: (object(),))
    runtime._assembler = SimpleNamespace(add=lambda part: message)
    runtime._carrier_requested_at = now
    runtime._carrier_number = "10001"
    monkeypatch.setattr("fourg_bridge.app.runtime.decode_pdu", lambda raw: raw)
    assert runtime.poll_sms(relay_enabled=False) is None
    assert runtime.carrier_usage.fraction == 0.2
    assert runtime.carrier_reply_received
    assert not runtime.carrier_pending


def test_pending_query_does_not_send_again():
    import time

    from fourg_bridge.app.runtime import ModemRuntime

    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._carrier_deadline = time.monotonic() + 600
    assert "没有重复发送" in runtime.query_carrier("10001", "108")
