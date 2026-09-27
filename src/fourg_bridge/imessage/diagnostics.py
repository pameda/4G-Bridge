"""Safe, localized diagnostics: never include raw AppleScript output or recipients."""

import re

from fourg_bridge.models import RelayError, RelayResult

_ERROR_CODE = re.compile(r"AppleScript error (-?\d{1,6})\Z")
_REASONS = {
    RelayError.NONE: "无",
    RelayError.MESSAGES_UNAVAILABLE: "信息应用不可用",
    RelayError.AUTOMATION_DENIED: "自动化权限拒绝",
    RelayError.IMESSAGE_NOT_CONNECTED: "iMessage 服务未连接",
    RelayError.TARGET_UNAVAILABLE: "接收目标不可用",
    RelayError.SCRIPT_TIMEOUT: "系统响应超时",
    RelayError.SCRIPT_FAILED: "系统脚本执行失败",
    RelayError.TARGET_INVALID: "目标格式无效",
    RelayError.KEYCHAIN_UNAVAILABLE: "钥匙串不可读取",
}


def relay_diagnostic(result: RelayResult, *, send: bool) -> str:
    operation = "测试发送" if send else "连接检查"
    if result.accepted:
        return (
            f"{operation}：Messages 已接受请求；尚未验证对端送达。"
            if send
            else f"{operation}：本机前置检查通过；尚未验证实际发送。"
        )
    stage = "发送阶段，结果待核实" if result.delivery_uncertain else "未获成功确认"
    reason = _REASONS.get(result.error, "未知错误")
    match = _ERROR_CODE.fullmatch(result.detail)
    code = f" · 系统错误码 {int(match[1])}" if match else ""
    return f"{operation}：{stage} · {reason}{code}"
