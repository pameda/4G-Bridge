from __future__ import annotations

import subprocess
import time
from contextlib import suppress
from dataclasses import replace
from datetime import datetime

from fourg_bridge.cellular.data_control import ModemAttachControl, NetworkSetupControl
from fourg_bridge.imessage.bridge import MessagesBridge
from fourg_bridge.models import DataState, ModemSnapshot, RelayStatus
from fourg_bridge.modem.controller import ModemController
from fourg_bridge.modem.usb_discovery import USBDiscovery
from fourg_bridge.modem.usb_session import USBModemSession, USBSessionFactory
from fourg_bridge.network.data_session import DataSessionManager, DataTransition
from fourg_bridge.network.ecm import ECMDetector
from fourg_bridge.network.traffic import TrafficLedger, TrafficMonitor, TrafficUsage
from fourg_bridge.sms.assembler import SMSAssembler
from fourg_bridge.sms.pdu_decoder import PDUDecodeError, decode_pdu
from fourg_bridge.sms.receiver import SMSReceiver
from fourg_bridge.sms.relay import SMSRelay
from fourg_bridge.storage.database import RelayDatabase
from fourg_bridge.support.privacy import redact_identifier


class ModemRuntime:
    def __init__(
        self,
        discovery: USBDiscovery,
        database: RelayDatabase,
        bridge: MessagesBridge,
    ) -> None:
        descriptor = discovery.discover()
        if descriptor is None:
            raise OSError("QDC507 not present")
        self._discovery = discovery
        self._database = database
        self._bridge = bridge
        self._enable_cancelled = False
        self._session: USBModemSession = USBSessionFactory(discovery).connect(descriptor)
        self._controller = ModemController(discovery, self._session.transport)
        self._receiver = SMSReceiver(self._session.transport)
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

    def poll_sms(self) -> str | None:
        recent: str | None = None
        self._relay.retry_cleanup()
        for raw in self._receiver.poll():
            try:
                part = decode_pdu(raw)
            except PDUDecodeError:
                continue
            message = self._assembler.add(part)
            if message is None:
                continue
            record = self._relay.enqueue(message)
            if record.status in (RelayStatus.SENT, RelayStatus.CLEANUP_PENDING):
                time = datetime.fromisoformat(record.timestamp).astimezone().strftime("%H:%M")
                recent = f"{time} / {redact_identifier(record.sender)}"
        return recent

    def set_data(self, enabled: bool, user_confirmed: bool = False) -> DataTransition | None:
        if self._data is None:
            return None
        if enabled and user_confirmed:
            self._enable_cancelled = False
        result = self._data.set_enabled(enabled, user_confirmed)
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
                    return self._data.set_enabled(True, user_confirmed=True)
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
        self._bound_interface = (interface.device, interface.service)
