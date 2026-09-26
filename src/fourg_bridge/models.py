from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class DeviceState(StrEnum):
    MISSING = "missing"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class SIMState(StrEnum):
    UNKNOWN = "unknown"
    READY = "ready"
    NOT_READY = "not_ready"
    MISSING = "missing"
    PIN_REQUIRED = "pin_required"


class RegistrationState(StrEnum):
    UNKNOWN = "unknown"
    NOT_REGISTERED = "not_registered"
    REGISTERED_HOME = "registered_home"
    SEARCHING = "searching"
    DENIED = "denied"
    REGISTERED_ROAMING = "registered_roaming"


class DataState(StrEnum):
    OFF = "off"
    ENABLING = "enabling"
    ON = "on"
    DISABLING = "disabling"
    PROTECTION_FAILED = "protection_failed"


class RelayStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    RETRY = "retry"
    SENT = "sent"
    DELIVERY_UNKNOWN = "delivery_unknown"
    CLEANUP_PENDING = "cleanup_pending"
    CLEANUP_BLOCKED = "cleanup_blocked"
    FAILED = "failed"


class RelayError(StrEnum):
    NONE = "none"
    MESSAGES_UNAVAILABLE = "messages_unavailable"
    AUTOMATION_DENIED = "automation_denied"
    IMESSAGE_NOT_CONNECTED = "imessage_not_connected"
    TARGET_UNAVAILABLE = "target_unavailable"
    SCRIPT_TIMEOUT = "script_timeout"
    SCRIPT_FAILED = "script_failed"
    TARGET_INVALID = "target_invalid"
    KEYCHAIN_UNAVAILABLE = "keychain_unavailable"


@dataclass(frozen=True, slots=True)
class DeviceDescriptor:
    vendor_id: int
    product_id: int
    manufacturer: str | None = None
    product: str | None = None
    serial_number: str | None = None


@dataclass(frozen=True, slots=True)
class ATResponse:
    lines: tuple[str, ...]
    final: str
    raw: bytes = field(repr=False, default=b"")

    @property
    def ok(self) -> bool:
        return self.final == "OK"


@dataclass(frozen=True, slots=True)
class ModemSnapshot:
    device_state: DeviceState = DeviceState.MISSING
    descriptor: DeviceDescriptor | None = None
    modem_identity: str | None = None
    usb_configuration: str | None = None
    sim_state: SIMState = SIMState.UNKNOWN
    iccid: str | None = field(default=None, repr=False)
    phone_number: str | None = field(default=None, repr=False)
    operator: str | None = None
    registration: RegistrationState = RegistrationState.UNKNOWN
    rat: str | None = None
    csq: int | None = None
    rssi_dbm: int | None = None
    interface: str | None = None
    network_service: str | None = None
    ipv4: str | None = None
    gateway: str | None = None
    default_interface: str | None = None
    vpn_active: bool = False
    data_state: DataState = DataState.OFF
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class RawSMSPart:
    storage: str
    index: int
    pdu: str


@dataclass(frozen=True, slots=True)
class CleanupProof:
    storage: str
    index: int
    pdu_hash: str
    identity: str


@dataclass(frozen=True, slots=True)
class DecodedSMSPart:
    sender: str
    timestamp: datetime
    text: str
    raw_pdu: str
    storage: str
    index: int
    concat_ref: int | None = None
    concat_total: int = 1
    concat_sequence: int = 1


@dataclass(frozen=True, slots=True)
class AssembledSMS:
    sender: str
    timestamp: datetime
    body: str = field(repr=False)
    ordered_pdus: tuple[str, ...] = field(repr=False)
    locations: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class RelayResult:
    accepted: bool
    error: RelayError = RelayError.NONE
    detail: str = ""
    delivery_uncertain: bool = False


@dataclass(frozen=True, slots=True)
class TrafficSnapshot:
    interface: str
    sampled_at: datetime
    rx_bytes: int
    tx_bytes: int
    download_bps: float = 0
    upload_bps: float = 0
    session_rx_bytes: int = 0
    session_tx_bytes: int = 0
