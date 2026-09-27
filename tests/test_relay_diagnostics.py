import pytest

from fourg_bridge.imessage.diagnostics import relay_diagnostic
from fourg_bridge.models import RelayError, RelayResult
from fourg_bridge.support.event_log import EventLog


def test_uncertain_send_preserves_numeric_code_without_raw_output():
    result = RelayResult(False, RelayError.SCRIPT_FAILED, "AppleScript error -10000", True)
    text = relay_diagnostic(result, send=True)
    assert "系统错误码 -10000" in text
    assert "结果待核实" in text
    log = EventLog()
    log.add_bridge_result(result, send=True)
    assert "系统错误码 -10000" in log.text(True)


@pytest.mark.parametrize(
    "detail",
    [
        "test@example.invalid secret body (-10000)",
        "AppleScript error -10000\nsecret body",
        "AppleScript error 13800138000",
    ],
)
def test_diagnostic_rejects_private_freeform_data(detail):
    result = RelayResult(False, RelayError.SCRIPT_FAILED, detail, True)
    log = EventLog()
    log.add_bridge_result(result, send=True)
    assert "secret" not in log.text()
    assert "@" not in log.text()
    assert "13800138000" not in log.text()
    assert "系统错误码" not in log.text()


@pytest.mark.parametrize("error", list(RelayError))
def test_all_error_types_have_localized_diagnostics(error):
    text = relay_diagnostic(RelayResult(False, error), send=False)
    assert "连接检查" in text


def test_check_success_never_claims_delivery():
    assert "尚未验证实际发送" in relay_diagnostic(RelayResult(True), send=False)
    assert "尚未验证对端送达" in relay_diagnostic(RelayResult(True), send=True)
