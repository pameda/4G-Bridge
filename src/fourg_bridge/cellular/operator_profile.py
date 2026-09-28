"""Read-only carrier query profiles; never infer a carrier from a phone prefix.

COPS reports the currently registered operator (including ported SIMs). Unknown,
foreign and roaming networks fail closed. Only exact known aliases are accepted.
"""

from dataclasses import dataclass

from fourg_bridge.models import ModemSnapshot, RegistrationState, SIMState


@dataclass(frozen=True, slots=True)
class OperatorProfile:
    name: str
    number: str
    command: str


TELECOM = OperatorProfile("中国电信", "10001", "108")
UNICOM = OperatorProfile("中国联通", "10010", "CXTCYL")
MOBILE = OperatorProfile("中国移动", "10086", "CXLL")

_ALIASES = {
    **dict.fromkeys(
        ("中国电信", "CHN-CT", "CHINA TELECOM", "CTCC", "46003", "46005", "46011"), TELECOM
    ),
    **dict.fromkeys(
        ("中国联通", "CHN-UNICOM", "CHINA UNICOM", "UNICOM", "46001", "46006", "46009"), UNICOM
    ),
    **dict.fromkeys(
        ("中国移动", "CHINA MOBILE", "CMCC", "CHN-CMCC", "46000", "46002", "46007", "46008"), MOBILE
    ),
}


def operator_profile(snapshot: ModemSnapshot) -> OperatorProfile | None:
    if (
        not snapshot.descriptor
        or not snapshot.iccid
        or snapshot.sim_state != SIMState.READY
        or snapshot.registration != RegistrationState.REGISTERED_HOME
    ):
        return None
    return _ALIASES.get((snapshot.operator or "").strip().upper())
