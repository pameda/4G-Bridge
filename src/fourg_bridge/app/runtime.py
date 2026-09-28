from __future__ import annotations

import subprocess
import time
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timedelta

from fourg_bridge.cellular.carrier_query import (
    parse_allowance,
    parse_unicom_notice,
    parse_usage,
    query_response_issue,
    send_query,
)
from fourg_bridge.cellular.data_control import ModemAttachControl, NetworkSetupControl
from fourg_bridge.cellular.operator_profile import UNICOM, operator_profile
from fourg_bridge.imessage.bridge import MessagesBridge
from fourg_bridge.models import DataState, ModemSnapshot, RelayStatus, SIMState
from fourg_bridge.modem.controller import ModemController
from fourg_bridge.modem.usb_discovery import USBDiscovery
from fourg_bridge.modem.usb_session import USBModemSession, USBSessionFactory
from fourg_bridge.network.data_session import DataSessionManager, DataTransition
from fourg_bridge.network.ecm import ECMDetector
from fourg_bridge.network.traffic import TrafficLedger, TrafficMonitor, TrafficUsage
from fourg_bridge.sms.assembler import SMSAssembler
from fourg_bridge.sms.inbox import SMSInbox
from fourg_bridge.sms.pdu_decoder import PDUDecodeError, decode_pdu
from fourg_bridge.sms.receiver import SMSReceiver
from fourg_bridge.sms.relay import SMSRelay
from fourg_bridge.storage.auto_query import matches_profile
from fourg_bridge.storage.database import RelayDatabase
from fourg_bridge.storage.identity import IdentityStore
from fourg_bridge.support.privacy import redact_identifier, stable_message_hash


class ModemRuntime:
    def __init__(
        self,
        discovery: USBDiscovery,
        database: RelayDatabase,
        bridge: MessagesBridge,
        inbox: SMSInbox | None = None,
    ) -> None:
        descriptor = discovery.discover()
        if descriptor is None:
            raise OSError("QDC507 not present")
        self._discovery = discovery
        self._database = database
        self._bridge = bridge
        self.inbox = inbox if inbox is not None else SMSInbox()
        self._enable_cancelled = False
        self.carrier_allowance = None
        self.carrier_usage = None
        self.carrier_reply_received = False
        self.carrier_problem = ""
        self.carrier_cache_pending = True
        self._carrier_cache_at = None
        self._carrier_deadline = 0.0
        self._carrier_requested_at = None
        self._carrier_number = None
        self._carrier_query_sim = None
        self._session: USBModemSession = USBSessionFactory(discovery).connect(descriptor)
        self._controller = ModemController(discovery, self._session.transport)
        self._receiver = SMSReceiver(
            self._session.transport, identity=IdentityStore(database.path.parent)
        )
        self._sms_identity = None
        self.carrier_sim_key = None
        self._assembler = SMSAssembler()
        self._relay = SMSRelay(database, bridge, self._receiver)
        self._relay.recover_interrupted()
        self._ecm = ECMDetector()
        self._traffic = TrafficMonitor()
        self._traffic_ledger = TrafficLedger(database.path.parent / "traffic.sqlite")
        self.traffic_snapshot = None
        self.traffic_usage = TrafficUsage()
        self._data: DataSessionManager | None = None
        self._bound_interface: tuple[str, str | None] | None = None
        with suppress(OSError):
            self._bind_data_manager()

    def snapshot(self) -> ModemSnapshot:
        snapshot = self._controller.snapshot()
        snapshot = replace(snapshot, data_state=self._data.state if self._data else DataState.OFF)
        try:
            return self._network_snapshot(snapshot)
        except (OSError, subprocess.SubprocessError):
            # ECM/DHCP is not a prerequisite for SMS over the AT channel.
            # A Wi-Fi-only Mac can still relay using Messages' own network.
            return replace(
                snapshot,
                data_state=self._data.state if self._data else DataState.OFF,
                warning="网络状态暂不可读；短信转发不依赖 4G 数据开关。",
            )

    def _network_snapshot(self, snapshot: ModemSnapshot) -> ModemSnapshot:
        self.traffic_snapshot = None
        try:
            interface = self._ecm.discover()
        except OSError:
            interface = None
        if interface:
            if self._data is None or self._bound_interface != (interface.device, interface.service):
                self.force_safe_off()
                self._bind_data_manager()
            snapshot = replace(
                snapshot,
                interface=interface.device,
                network_service=interface.service,
                ipv4=self._ecm.ipv4(interface.device),
                gateway=self._ecm.gateway(interface.device),
                default_interface=self._ecm.default_interface(),
                vpn_active=self._ecm.has_vpn(),
                data_state=self._data.state if self._data else DataState.OFF,
            )
            try:
                self.traffic_snapshot = self._traffic.sample(interface.device)
                self.traffic_usage = self._traffic_ledger.record(self.traffic_snapshot)
            except (OSError, ValueError, subprocess.SubprocessError):
                self.traffic_snapshot = None
        self.traffic_usage = self._traffic_ledger.usage()
        return snapshot

    @property
    def carrier_pending(self):
        return time.monotonic() < self._carrier_deadline

    def restore_carrier_query(self, key, number, stamp):
        """Resume reading the existing query's reply without submitting another SMS."""
        if self._carrier_requested_at is not None:
            return
        self._carrier_query_sim = key
        self._carrier_number = number
        self._carrier_requested_at = datetime.fromtimestamp(stamp).astimezone()
        self._carrier_deadline = time.monotonic() + 600

    def query_carrier(self, number, command, *, expected_sim=None, operator=None, authorized=None):
        if self.carrier_pending:
            return "仍在等待上次回复，最多等待 10 分钟；没有重复发送。"
        # Serialize validation and submission with every other AT transaction.
        with self._session.transport.transaction():
            if expected_sim:
                snapshot = self._controller.snapshot()
                key = IdentityStore(self._database.path.parent).sim(snapshot.iccid)
                if key != expected_sim or (operator and not matches_profile(snapshot, operator)):
                    return "SIM 或运营商已变化，未发送查询；请重新确认。"
                if snapshot.sim_state != SIMState.READY:
                    return "SIM 尚未就绪，未发送查询。"
                self._receiver.read_identity()
                if self._receiver.sim_key != expected_sim:
                    return "SIM 已变化或无法核实，未发送查询。"
            if authorized is not None and not authorized():
                return "自动查询授权已关闭或修改，未发送。"
            self._carrier_query_sim = expected_sim
            return self._submit_carrier_query(number, command)

    def _submit_carrier_query(self, number, command):
        if self.carrier_pending:
            return "仍在等待上次回复，最多等待 10 分钟；没有重复发送。"
        self._carrier_requested_at = datetime.now().astimezone().replace(microsecond=0)
        self.carrier_reply_received = False
        self.carrier_problem = ""
        self.carrier_allowance = None
        self.carrier_usage = None
        self._carrier_number = number
        self._carrier_deadline = time.monotonic() + 600
        return send_query(self._session.transport, number, command, confirmed=True)

    def poll_sms(self, *, relay_enabled: bool = True) -> str | None:
        recent: str | None = None
        self._last_sms_hashes = set()
        relay_enabled = relay_enabled and not self._database.blocked
        if relay_enabled:
            self._relay.retry_cleanup()
        parts = self._receiver.poll()
        identity = (self._receiver.identity, self._receiver.sim_key)
        self.inbox.bind(identity)
        if self._sms_identity != identity:
            self._assembler = SMSAssembler()
            self.carrier_usage = None
            self.carrier_allowance = None
            self.carrier_sim_key = None
            self._carrier_cache_at = None
            self.carrier_reply_received = False
            self.carrier_problem = ""
            if getattr(self, "_carrier_query_sim", None) != identity[1]:
                self._carrier_requested_at = None
                self._carrier_number = None
                self._carrier_deadline = 0.0
            self._sms_identity = identity
        for raw in parts:
            try:
                part = decode_pdu(raw)
            except PDUDecodeError:
                continue
            message = self._assembler.add(part)
            if message is None:
                continue
            self.inbox.add(message)
            self._last_sms_hashes.add(
                stable_message_hash(
                    message.sender, message.timestamp.isoformat(), message.ordered_pdus
                )
            )
            notice_applied = self._accept_carrier_notice(message)
            if not notice_applied and (
                message.sender in ("10001", "10086", "10010")
                and getattr(self, "_carrier_requested_at", None) is not None
                and getattr(self, "_carrier_query_sim", None) == self._receiver.sim_key
                and message.timestamp
                >= (
                    getattr(self, "_carrier_requested_at", None)
                    or datetime.now().astimezone() - timedelta(days=1)
                )
                and (
                    getattr(self, "_carrier_number", None) is None
                    or message.sender == self._carrier_number
                )
                and (
                    getattr(self, "_carrier_cache_at", None) is None
                    or message.timestamp >= self._carrier_cache_at
                )
            ):
                self.carrier_reply_received = True
                self._carrier_cache_at = message.timestamp
                allowance = parse_allowance(message.sender, message.body, message.timestamp)
                usage = parse_usage(message.sender, message.body, message.timestamp)
                if usage:
                    self.carrier_usage = usage
                    self.carrier_sim_key = self._receiver.sim_key
                    self._carrier_deadline = 0
                    self.carrier_problem = ""
                else:
                    self.carrier_problem = query_response_issue(message.body)
                    self._carrier_deadline = 0
                if allowance:
                    self.carrier_allowance = allowance
                    self.carrier_sim_key = self._receiver.sim_key
                    self._carrier_deadline = 0
            if not relay_enabled:
                continue  # Query replies stay on the module until successfully relayed.
            record = self._relay.enqueue(message)
            if record.status in (RelayStatus.SENT, RelayStatus.CLEANUP_PENDING):
                time = datetime.fromisoformat(record.timestamp).astimezone().strftime("%H:%M")
                recent = f"{time} / {redact_identifier(record.sender)}"
        for entry in self.inbox.snapshot():
            record = self._database.get(entry.message_hash)
            if record:
                self.inbox.set_status(entry.message_hash, record.status)
        self.carrier_cache_pending = False
        return recent

    def _accept_carrier_notice(self, message):
        """Accept unsolicited usage notices only for a verified current home SIM."""
        usage = parse_unicom_notice(message.sender, message.body, message.timestamp)
        if not usage or not self._receiver.sim_key:
            return False
        age = datetime.now().astimezone() - message.timestamp
        cached = getattr(self, "_carrier_cache_at", None)
        if not timedelta(0) <= age <= timedelta(hours=6) or (cached and usage.timestamp <= cached):
            return False
        try:
            snapshot = self._controller.snapshot()  # AT only; independent of ECM/Wi-Fi.
            key = IdentityStore(self._database.path.parent).sim(snapshot.iccid)
            if key != self._receiver.sim_key or operator_profile(snapshot) != UNICOM:
                return False
        except Exception:
            return False  # A failed status query must not interrupt ordinary SMS relay.
        self.carrier_usage = usage
        self.carrier_allowance = parse_allowance(message.sender, message.body, message.timestamp)
        self.carrier_sim_key = key
        self.carrier_reply_received = True
        self.carrier_problem = ""
        self._carrier_cache_at = message.timestamp
        self._carrier_deadline = 0
        return True

    def prepare_backfill(self, keys, identity):
        """Re-read current SIM first; never resurrect messages from memory alone."""
        if self._database.blocked or not identity or not all(identity):
            return 0
        self.poll_sms(relay_enabled=False)
        if self._sms_identity != identity:
            return 0
        queued = 0
        for key in set(keys) & self._last_sms_hashes:
            record = self._database.get(key)
            if record is None:
                queued += 1  # Normal polling creates its first pending record.
            elif self._database.retry_unsent(key):
                self.inbox.set_status(key, RelayStatus.RETRY)
                queued += 1
        return queued

    def set_data(
        self, enabled: bool, user_confirmed: bool = False, *, automatic: bool = False
    ) -> DataTransition | None:
        if self._data is None:
            return None
        if enabled and user_confirmed:
            self._enable_cancelled = False
        result = self._data.set_enabled(enabled, user_confirmed, prefer_cellular=automatic)
        if enabled and user_confirmed and self._enable_cancelled:
            return self._data.force_safe_off()
        if not (
            enabled and user_confirmed and result.code == "network_not_ready" and result.protected
        ):
            return result
        # Some QDC507/macOS ECM combinations do not recover link after a
        # service disable/enable. One bounded restart belongs only to this
        # explicit enable request, never to polling or USB reconnect.
        try:
            response = self._session.transport.transact("AT+CFUN=1,1", timeout=8)
            if not response.ok:
                return result
            self._session.close()
            self._data = None
            self._bound_interface = None
            deadline = time.monotonic() + 60
            time.sleep(8)
            while time.monotonic() < deadline:
                if self._enable_cancelled:
                    return DataTransition(DataState.OFF, DataState.OFF, True, "连接已取消")
                descriptor = self._discovery.discover()
                if descriptor is None:
                    time.sleep(1)
                    continue
                try:
                    session = USBSessionFactory(self._discovery).connect(descriptor)
                except (OSError, RuntimeError):
                    time.sleep(1)
                    continue
                self._session = session
                self._controller = ModemController(self._discovery, session.transport)
                self._receiver = SMSReceiver(session.transport)
                self._assembler = SMSAssembler()
                self._relay = SMSRelay(self._database, self._bridge, self._receiver)
                self._bind_data_manager()
                if self._data is not None:
                    if self._enable_cancelled:
                        return self._data.force_safe_off()
                    return self._data.set_enabled(
                        True, user_confirmed=True, prefer_cellular=automatic
                    )
                session.close()
                time.sleep(1)
        except Exception:
            rollback = self.force_safe_off()
            if rollback is not None and not rollback.protected:
                return rollback
        return DataTransition(
            DataState.OFF,
            DataState.OFF,
            True,
            "模块重启后未能恢复连接，数据已关闭。请检查 USB 连接后重新检测。",
            "recovery_failed",
        )

    def force_safe_off(self) -> DataTransition | None:
        self.cancel_pending_enable()
        if self._data is None:
            return None
        return self._data.force_safe_off()

    def cancel_pending_enable(self) -> None:
        # Called before acquiring the runtime lock on sleep/wake/quit.
        self._enable_cancelled = True

    def close(self) -> None:
        self.force_safe_off()
        self._session.close()

    def _bind_data_manager(self) -> None:
        interface = self._ecm.discover()
        if interface is None or not interface.service:
            return
        self._data = DataSessionManager(
            interface.service,
            NetworkSetupControl(interface.device),
            ModemAttachControl(self._session.transport),
        )
        self._data.force_safe_off()
        # Recover a previous temporary failover order after a crash/restart.
        NetworkSetupControl(interface.device).ensure_wifi_precedes(interface.service)
        self._bound_interface = (interface.device, interface.service)
