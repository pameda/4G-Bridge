"""Headless Windows coordinator. UI never touches USB or waits for system commands."""

from __future__ import annotations

import hashlib
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fourg_bridge.cellular.carrier_query import parse_usage, send_query
from fourg_bridge.models import TrafficSnapshot
from fourg_bridge.modem.at_parser import parse_csq, parse_registration
from fourg_bridge.modem.at_transport import ATTransport
from fourg_bridge.network.failover import Action
from fourg_bridge.network.traffic import TrafficLedger
from fourg_bridge.sms.assembler import SMSAssembler
from fourg_bridge.sms.pdu_decoder import decode_pdu
from fourg_bridge.sms.receiver import SMSReceiver
from fourg_bridge.storage.carrier_budget import CarrierBudgetStore
from fourg_bridge.support.event_log import EVENTS, EventLog
from fourg_bridge.windows import native, platform
from fourg_bridge.windows.diagnostics import MESSAGES, Diagnostic, diagnostic
from fourg_bridge.windows.metric import MetricLease
from fourg_bridge.windows.notifications import NetworkNotifications
from fourg_bridge.windows.policy import ControllerPolicy
from fourg_bridge.windows.probe import ProbeRunner
from fourg_bridge.windows.settings import Preferences


@dataclass(frozen=True)
class UIEvent:
    kind: str
    message: str = ""


@dataclass(frozen=True)
class QueryRequest:
    number: str
    code: str
    sim_key: str
    created: float

    def valid(self, sim_key: str, now: float) -> bool:
        return self.sim_key == sim_key and bool(sim_key) and 0 <= now - self.created <= 60


class Runtime:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.preferences = Preferences.load(directory / "settings.json")
        self.budget = CarrierBudgetStore(directory / "carrier.sqlite")
        self.ledger = TrafficLedger(directory / "traffic.sqlite")
        self.metric = MetricLease(directory / "metric-lease.json")
        self.events: queue.Queue[UIEvent] = queue.Queue()
        self.commands: queue.Queue[str] = queue.Queue(maxsize=16)
        self.sms_commands: queue.Queue[QueryRequest] = queue.Queue(maxsize=1)
        self._query_pending = threading.Event()
        self.log = EventLog(
            catalog=EVENTS
            | {
                "win_" + code: ("信息", "连接诊断", title + "；" + action)
                for code, (title, action) in MESSAGES.items()
            }
        )
        self.diagnostic: Diagnostic = diagnostic("missing")
        self.log.add("start")
        self.inventory = platform.Inventory()
        self.policy = ControllerPolicy()
        self.status = "正在检测设备…"
        self.modem_status = "等待 AT 串口"
        self.data_on = False
        self._manual_connection = False
        self.sim_verified = False
        self.registered = False
        self._sim_key = ""
        self.protection_failed = False
        self.wifi_online: bool | None = None
        self.traffic = TrafficSnapshot("", datetime.now().astimezone(), 0, 0)
        self._stop = threading.Event()
        self._closing = threading.Event()
        self._suspended = threading.Event()
        self._control_lock = threading.RLock()
        self._change_lock = threading.RLock()
        self._cancel_enable = threading.Event()
        self._enabling = False
        self._network_epoch = 0
        self._probe = ProbeRunner()
        self._notifications = NetworkNotifications(self._network_changed)
        self._adapter: platform.Adapter | None = None
        self._guard_thread = threading.Thread(target=self._guard, daemon=True)
        self._net_thread = threading.Thread(target=self._network_loop, daemon=True)
        self._sms_thread = threading.Thread(target=self._sms_loop, daemon=True)
        self._last_reason = ""
        self._last_sample: tuple[str, float, int, int] | None = None
        self._session_rx = self._session_tx = 0
        self._refresh = threading.Event()

    def start(self) -> None:
        if not self._notifications.start():
            self._notify("系统网络事件不可用，已保留两秒轮询检测。")
        self._net_thread.start()
        self._guard_thread.start()
        self._sms_thread.start()

    def command(self, action: str) -> None:
        if action not in {"on", "off", "rescan", "sleep", "wake"}:
            raise ValueError("unknown action")
        self._network_epoch += 1
        if action == "on":
            self._cancel_enable.clear()
        else:
            self._cancel_enable.set()
        if action == "off":
            self.preferences.auto_takeover = False
        if action in {"sleep", "wake"}:
            self._suspended.set()
            self.budget.approved = False
        try:
            self.commands.put_nowait(action)
        except queue.Full:
            self.events.put(UIEvent("error", "操作进行中，请稍候"))
        self._refresh.set()

    def authorize_auto(self, enabled: bool) -> None:
        if enabled and not native.is_admin():
            raise platform.PlatformError("自动接管需要管理员权限，请使用设置中的重新启动按钮")
        self.preferences.auto_takeover = enabled
        self.preferences.save(self.directory / "settings.json")
        self.policy = ControllerPolicy()
        if not enabled:
            self.command("off")
        self._refresh.set()

    def query(self, number: str, code: str) -> None:
        # The UI obtains explicit consent. Validate before queuing, never retry.
        from fourg_bridge.cellular.carrier_query import query_pdu

        query_pdu(number, code)
        if not self.sim_verified:
            raise platform.PlatformError("SIM 或 AT 通道尚未验证，未发送查询")
        if self._query_pending.is_set():
            raise platform.PlatformError("查询进行中，请等待回复，不重复发送")
        self._query_pending.set()
        try:
            self.sms_commands.put_nowait(
                QueryRequest(number, code, self._sim_key, time.monotonic())
            )
        except queue.Full as exc:
            raise platform.PlatformError("已有查询等待执行，不重复发送") from exc

    def _notify(self, message: str) -> None:
        self.status = message
        self.events.put(UIEvent("refresh"))

    def _network_changed(self) -> None:
        self._network_epoch += 1
        self._refresh.set()

    def _diagnose(self, code: str) -> None:
        state = diagnostic(code)
        if state != self.diagnostic:
            self.log.add("win_" + state.code)
        self.diagnostic = state

    def _reason(self) -> str:
        if self._adapter is None:
            return "missing"
        if self.protection_failed:
            return "protection"
        if not native.is_admin():
            return "permission"
        if not self.sim_verified:
            return "sim"
        if not self.registered:
            return "registration"
        state = self.budget.status().state
        if state != "ready":
            return state
        if self._enabling:
            return "address"
        if self.wifi_online:
            return "wifi"
        if not (self.preferences.auto_takeover or self._manual_connection):
            return "disabled"
        return "ready"

    def _change(self, enabled: bool) -> bool:
        # Long OS operations serialize transitions, not metering or quota observation.
        with self._change_lock:
            self._enabling = enabled
            try:
                return self._perform_change(enabled)
            finally:
                self._enabling = False
                self._diagnose(self._reason())

    def _perform_change(self, enabled: bool) -> bool:
        adapter = self._adapter
        if adapter is None:
            self.data_on = False
            self._manual_connection = False
            return not enabled
        if enabled and (
            self._closing.is_set()
            or self._suspended.is_set()
            or self.budget.status().state != "ready"
            or not self.sim_verified
            or not self.registered
            or self.protection_failed
            or self._cancel_enable.is_set()
        ):
            self._notify("尚未满足开启条件：检查 SIM、套餐快照及保护状态")
            return False
        if not enabled and not adapter.enabled and not self.metric.path.exists():
            self.data_on = False
            self._manual_connection = False
            self.protection_failed = False
            self.budget.approved = False
            return True
        if not native.is_admin():
            self.protection_failed = adapter.enabled
            self._notify("网络控制需要管理员权限；尚未执行自动接管或保证数据关闭")
            return False
        self.log.add("data_transition")
        try:
            if enabled:
                with self._control_lock:
                    self._sample(adapter)
                self.metric.acquire(adapter.guid)
                if self.budget.status().state != "ready" or self._cancel_enable.is_set():
                    self.metric.restore(adapter.guid)
                    return False
            platform.change_adapter(adapter.guid, enabled)
            self._notify("等待模块取得 IP 地址…" if enabled else "正在验证数据关闭…")
            deadline = time.monotonic() + (25 if enabled else 8)
            while time.monotonic() < deadline:
                if enabled and (
                    self._cancel_enable.is_set()
                    or self.budget.status().state != "ready"
                    or not self.sim_verified
                    or not self.registered
                    or self._suspended.is_set()
                ):
                    break
                snapshot = platform.inventory()
                actual = snapshot.modem()
                self.inventory = snapshot
                if not enabled and (actual is None or not actual.enabled):
                    if actual:
                        self.metric.restore(adapter.guid)
                    self.data_on = False
                    self._manual_connection = False
                    self.protection_failed = False
                    self.budget.approved = False
                    self.log.add("data_off")
                    self._notify("4G 数据已关闭；短信查询仍可使用")
                    return True
                if (
                    enabled
                    and actual
                    and actual.guid == adapter.guid
                    and actual.usable
                    and actual.gateway
                    and not any(a.default and a.physical and not a.modem for a in snapshot.adapters)
                    and self.budget.status().state == "ready"
                    and not self._cancel_enable.is_set()
                    and not self._suspended.is_set()
                    and self.sim_verified
                    and self.registered
                ):
                    self.data_on = True
                    self._adapter = actual
                    self.protection_failed = False
                    self.log.add("data_on")
                    self._notify("4G 网卡已就绪；这不代表 VPN 或互联网端到端连通")
                    return True
                if self._closing.is_set() and enabled:
                    break
                time.sleep(0.5)
            if enabled:
                platform.change_adapter(adapter.guid, False)
                self.metric.restore(adapter.guid)
            raise platform.PlatformError("未取得可用地址或未能确认关闭")
        except Exception:
            if enabled:
                try:
                    platform.change_adapter(adapter.guid, False)
                    self.metric.restore(adapter.guid)
                except Exception:
                    pass
            # Do not log OS output, raw AT errors or identifiers.
            self.protection_failed = True
            self.log.add("warning")
            self._notify("网络切换未通过验证；请查看网卡／驱动。保护状态未确认")
            return False

    def _network_loop(self) -> None:
        previous_guid: str | None = None
        while not self._stop.is_set():
            self._refresh.clear()
            try:
                snapshot = platform.inventory()
                self.inventory = snapshot
                adapter = snapshot.modem()
                self._adapter = adapter
                self._diagnose(self._reason())
                guid = adapter.guid if adapter else None
                if guid != previous_guid:
                    self.data_on = False
                    self.sim_verified = False
                    self.budget.approved = False
                    self.policy = ControllerPolicy()
                    self._last_sample = None
                    if adapter:
                        self.log.add("connected")
                        self._change(False)
                    else:
                        self.log.add("missing")
                        self._notify("未发现唯一的兼容网卡；请检查 USB、系统驱动和设备页")
                    previous_guid = guid
                elif not adapter:
                    self._notify("未发现唯一兼容网卡；请检查 USB 及官方驱动")
                while not self.commands.empty():
                    command = self.commands.get_nowait()
                    if command == "on":
                        self.policy.failover.paused = False
                        ok = self._change(True)
                        self._manual_connection = ok
                        self.policy.failover.completed(Action.ENABLE, ok)
                    else:
                        if command == "off":
                            self.preferences.auto_takeover = False
                            self.preferences.save(self.directory / "settings.json")
                        safe = self._change(False)
                        if command == "wake" and safe:
                            self._suspended.clear()
                        if command in {"rescan", "wake"} and safe:
                            self._cancel_enable.clear()
                        self.policy = ControllerPolicy()
                if adapter:
                    # External enable is also subject to quota; do not claim it is OFF.
                    if adapter.enabled and not self.data_on and not self.protection_failed:
                        self._change(False)
                    wifi = [item for item in snapshot.adapters if item.wifi and item.usable]
                    epoch = self._network_epoch
                    probe_state = "offline"
                    if wifi:

                        def cancelled(version: int = epoch) -> bool:
                            return (
                                version != self._network_epoch
                                or self._closing.is_set()
                                or self._stop.is_set()
                                or self._suspended.is_set()
                            )

                        result = self._probe.run(
                            tuple((item.index, item.ipv4) for item in wifi),
                            cancelled,
                        )
                        self.wifi_online = result.online
                        probe_state = result.state
                    else:
                        self.wifi_online = False
                    if epoch != self._network_epoch:
                        continue
                    reason = self._reason()
                    self._diagnose(
                        "probe_timeout"
                        if reason == "ready" and probe_state == "timeout"
                        else "probe_error"
                        if reason == "ready" and probe_state == "error"
                        else reason
                    )
                    decision = self.policy.decide(
                        snapshot,
                        authorized=(self.preferences.auto_takeover or self._manual_connection)
                        and native.is_admin()
                        and self.sim_verified
                        and self.registered
                        and not self._suspended.is_set()
                        and not self.protection_failed,
                        budget=self.budget.status().state,
                        data_on=self.data_on,
                        wifi_online=self.wifi_online,
                    )
                    if decision.action != Action.HOLD:
                        ok = self._change(decision.action == Action.ENABLE)
                        self.policy.failover.completed(decision.action, ok)
                self.events.put(UIEvent("refresh"))
            except Exception:
                self.log.add("warning")
                self._notify("设备检测失败，已暂停自动接管；正在尝试安全关闭")
                self._change(False)
            self._refresh.wait(2)

    def _sample(self, adapter: platform.Adapter) -> None:
        rx, tx = native.interface_counters(adapter.index)
        now = time.monotonic()
        old = self._last_sample
        down = up = 0.0
        if old and old[0] == adapter.guid:
            elapsed = max(0.001, now - old[1])
            delta_rx = rx - old[2] if rx >= old[2] else rx
            delta_tx = tx - old[3] if tx >= old[3] else tx
            self._session_rx += delta_rx
            self._session_tx += delta_tx
            down, up = delta_rx / elapsed, delta_tx / elapsed
        self._last_sample = (adapter.guid, now, rx, tx)
        self.budget.observe(adapter.guid, self.inventory.boot, rx, tx)
        self.traffic = TrafficSnapshot(
            adapter.guid,
            datetime.now().astimezone(),
            rx,
            tx,
            down,
            up,
            self._session_rx,
            self._session_tx,
        )
        self.ledger.record(self.traffic)

    def _guard(self) -> None:
        while not self._stop.wait(1):
            adapter = self._adapter
            try:
                # Independent from AT, SMS and PowerShell inventory work.
                if adapter:
                    with self._control_lock:
                        self._sample(adapter)
                state = self.budget.status().state
                if (state != "ready" or not self.sim_verified or self._suspended.is_set()) and (
                    self.data_on or self._enabling
                ):
                    self._cancel_enable.set()
                    self._change(False)
                if state != self._last_reason:
                    self._last_reason = state
                    if state == "confirmation":
                        self.log.add("carrier80")
                        self.events.put(UIEvent("consent80"))
                    elif state in {"locked", "stale"}:
                        self.log.add("carrier98")
                        self.events.put(UIEvent("refresh"))
            except Exception:
                self.log.add("warning")
                self._cancel_enable.set()
                self._change(False)

    def _sms_loop(self) -> None:
        serial: native.SerialPort | None = None
        transport: ATTransport | None = None
        selected: str | None = None
        while not self._stop.is_set():
            try:
                candidates = [p for p in self.inventory.ports if "AT" in p.label.upper()]
                if not candidates:
                    candidates = (
                        list(self.inventory.ports) if len(self.inventory.ports) == 1 else []
                    )
                if sum(a.modem for a in self.inventory.adapters) > 1:
                    candidates = []
                # Probe one candidate at a time without opening the network USB interface.
                if transport and selected not in {p.name for p in candidates}:
                    transport.close()
                    if serial:
                        serial.close()
                    transport = serial = None
                if transport is None:
                    for port in candidates:
                        try:
                            serial = native.SerialPort(port.name)
                            transport = ATTransport(serial.write, serial.read)
                            if not transport.transact("AT", timeout=1).ok:
                                raise platform.PlatformError("非 AT 通道")
                            selected = port.name
                            break
                        except Exception:
                            if transport:
                                transport.close()
                            if serial:
                                serial.close()
                            transport = serial = None
                if transport:
                    self._read_modem(transport)
                    if not self.sms_commands.empty():
                        request = self.sms_commands.get_nowait()
                        if self.sim_verified and request.valid(self._sim_key, time.monotonic()):
                            self.log.add("query")
                            result = send_query(
                                transport, request.number, request.code, confirmed=True
                            )
                        else:
                            result = "SIM 已变化或确认已过期，未发送查询"
                        self._query_pending.clear()
                        self.log.add("query_end")
                        self.events.put(UIEvent("query_result", result))
                    # Read SMS only to extract carrier numbers. Never forward or delete.
                    assembler = SMSAssembler()
                    for part in SMSReceiver(transport).poll():
                        try:
                            message = assembler.add(decode_pdu(part))
                            if message:
                                usage = parse_usage(message.sender, message.body, message.timestamp)
                                if usage and self.sim_verified:
                                    old = self.budget.usage()
                                    self.budget.update_plan(usage)
                                    if old is None or usage.timestamp > old.timestamp:
                                        self.log.add("reply")
                        except (ValueError, IndexError):
                            continue
                else:
                    self.sim_verified = False
                    self.modem_status = "未发现可用 AT 串口；请检查官方驱动或是否被其他软件占用"
                    # Never leave a chargeable SMS queued to send unexpectedly on reconnect.
                    if not self.sms_commands.empty():
                        self.sms_commands.get_nowait()
                        self._query_pending.clear()
                        self.events.put(UIEvent("query_result", "AT 串口未就绪，未发送查询"))
            except Exception:
                self.sim_verified = False
                if self._query_pending.is_set():
                    while not self.sms_commands.empty():
                        self.sms_commands.get_nowait()
                    self._query_pending.clear()
                    self.events.put(
                        UIEvent("query_result", "查询中断，发送结果可能不确定；不会自动重发")
                    )
                self.modem_status = "AT 通信中断，将重新检测；不会自动重发查询"
                if transport:
                    transport.close()
                if serial:
                    serial.close()
                transport = serial = None
            self._stop.wait(5)
        if transport:
            transport.close()
        if serial:
            serial.close()

    def _read_modem(self, transport: ATTransport) -> None:
        responses: dict[str, Any] = {}
        for command in ("AT+CPIN?", "AT+QCCID", "AT+COPS?", "AT+CEREG?", "AT+QNWINFO", "AT+CSQ"):
            response = transport.transact(command, timeout=2)
            responses[command] = response.lines if response.ok else ()
        _, rssi = parse_csq(responses["AT+CSQ"])
        registration = parse_registration(responses["AT+CEREG?"])
        self.registered = registration in (1, 5)
        sim = (
            "就绪"
            if any(line.strip() == "+CPIN: READY" for line in responses["AT+CPIN?"])
            else "未就绪"
        )
        identifiers = re.findall(r"\b[0-9]{18,22}\b", " ".join(responses["AT+QCCID"]))
        verified = sim == "就绪" and len(identifiers) == 1
        if verified:
            sim_key = hashlib.sha256(identifiers[0].encode("ascii")).hexdigest()
            if sim_key != self._sim_key:
                self.sim_verified = False
                if self.data_on or self._enabling:
                    self._cancel_enable.set()
                    self._change(False)
            with self._control_lock:
                if sim_key != self._sim_key:
                    self.budget = CarrierBudgetStore(self.directory / f"carrier-{sim_key}.sqlite")
                    self._sim_key = sim_key
                    self._last_sample = None
                    if self.preferences.auto_takeover and not self._suspended.is_set():
                        self._cancel_enable.clear()
                self.sim_verified = True
        else:
            self.sim_verified = False
        operator = next(
            (line.split('"')[1] for line in responses["AT+COPS?"] if line.count('"') >= 2), "未知"
        )
        rat = next(
            (line.split('"')[1] for line in responses["AT+QNWINFO"] if line.count('"') >= 2), "未知"
        )
        self.modem_status = (
            f"SIM {sim} · {operator} · {rat}\n"
            f"注册状态 {registration} · 信号 {rssi if rssi is not None else '—'} dBm"
        )

    def shutdown(self) -> bool:
        self._closing.set()
        self._cancel_enable.set()
        self._network_changed()
        self.preferences.auto_takeover = False  # Memory only: never auto-enable during shutdown.
        ok = self._change(False)
        if ok:
            self._notifications.close()
            self._stop.set()
            self._refresh.set()
        else:
            self._closing.clear()
        return ok
