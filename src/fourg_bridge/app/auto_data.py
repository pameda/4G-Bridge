"""Independent quota guard and slow connectivity probe workers.

No Messages/USB lock is held while checking counters or disabling the service.
The UI controller owns all transitions; workers submit intents, not enable calls.
"""

from __future__ import annotations

import subprocess
import threading

from PyObjCTools import AppHelper

from fourg_bridge.cellular.data_control import NetworkSetupControl
from fourg_bridge.models import DataState
from fourg_bridge.network.connectivity import WiFiProbe
from fourg_bridge.network.ecm import ECMDetector
from fourg_bridge.network.failover import Action, FailoverPolicy, Observation
from fourg_bridge.network.traffic import TrafficMonitor


class AutoDataMonitor:
    def __init__(self, controller, budget):
        self.controller = controller
        self.budget = budget
        self.policy = FailoverPolicy()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.suspended = False
        self.status = "自动接管未开启"
        self.budget_status = None
        self.error = False
        self._traffic = TrafficMonitor()
        self._sample_lock = threading.Lock()
        self._boot = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.boottime"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()

    def start(self):
        for name, worker in (("Data-Quota", self._guard), ("WiFi-Health", self._probe)):
            threading.Thread(target=worker, name=name, daemon=True).start()

    def ready(self):
        settings = self.controller._settings
        try:
            self.budget_status = self.budget.status(settings.data_limit_bytes)
            if settings.data_limit_bytes <= 0:
                # Corrupt/missing settings must not bypass a previously used cap.
                return (
                    not settings.auto_data_enabled
                    and not self.error
                    and not self.budget_status.locked
                    and self.budget_status.used == 0
                )
            return not self.error and self.budget_status.available
        except Exception:
            self.error = True
            return False

    def reset(self):
        with self.lock:
            self.policy.reset()
            self.policy.paused = False

    def completed(self, enabled, success):
        with self.lock:
            self.policy.completed(Action.ENABLE if enabled else Action.DISABLE, success)
            if enabled and not success:
                self.status = "自动接管失败，已暂停；请检查模块后重新启用自动接管。"

    def sample(self):
        with self._sample_lock:
            self._sample()

    def _sample(self):
        settings = self.controller._settings
        snapshot = self.controller.current_snapshot()
        if not snapshot.interface or settings.data_limit_bytes <= 0:
            return
        sample = self._traffic.sample(snapshot.interface)
        self.budget_status = self.budget.observe(
            sample.interface,
            self._boot,
            sample.rx_bytes,
            sample.tx_bytes,
            settings.data_limit_bytes,
            monthly=settings.data_budget_period == "month",
        )

    def _guard(self):
        while not self.stop.is_set():
            settings = self.controller._settings
            if settings.data_limit_bytes > 0 and not self.suspended:
                try:
                    self.sample()
                except Exception:
                    # A bounded modem restart temporarily removes the interface.
                    # Ignore missing counters only if ECM is verifiably disabled.
                    snapshot = self.controller.current_snapshot()
                    try:
                        safely_restarting = (
                            snapshot.data_state == DataState.ENABLING
                            and snapshot.network_service
                            and not NetworkSetupControl().is_enabled(snapshot.network_service)
                        )
                    except Exception:
                        safely_restarting = False
                    if not safely_restarting:
                        self.error = True
                snapshot = self.controller.current_snapshot()
                if not self.ready() and snapshot.data_state in (
                    DataState.ON,
                    DataState.ENABLING,
                    DataState.PROTECTION_FAILED,
                ):
                    self.status = (
                        "计量不可用，保护性关闭 4G。"
                        if self.error
                        else "流量已达上限，4G 已锁定；需要手动追加额度。"
                    )
                    try:
                        self.controller.stop_for_budget()
                    except Exception:
                        self.error = True
            self.stop.wait(1)

    def _probe(self):
        probe = WiFiProbe()
        while not self.stop.is_set():
            settings = self.controller._settings
            snapshot = self.controller.current_snapshot()
            epoch = self.controller._data_epoch
            if (
                settings.auto_data_enabled
                and not self.suspended
                and not self.controller._data_busy
                and snapshot.descriptor
                and snapshot.data_state in (DataState.OFF, DataState.ON)
                and self.ready()
            ):
                try:
                    interface = probe.interface()
                    vpn = ECMDetector.has_vpn()
                    default = ECMDetector.default_interface()
                    other = bool(default and default not in (interface, snapshot.interface))
                    wifi_online = None if vpn or other else probe.online(interface)
                    observation = Observation(
                        True,
                        True,
                        True,
                        snapshot.data_state == DataState.ON,
                        wifi_online,
                        vpn,
                        other,
                    )
                    with self.lock:
                        action = self.policy.decide(observation)
                        if not self.policy.paused:
                            self.status = (
                                "VPN／其他优先网络存在，自动接管暂缓。"
                                if vpn or other
                                else "Wi-Fi 可用，优先使用 Wi-Fi。"
                                if wifi_online
                                else "正在使用 4G 接管。"
                                if self.policy.owned
                                else f"Wi-Fi 无互联网，确认中（{self.policy.failures}/3）。"
                            )
                    if action != Action.HOLD:
                        AppHelper.callAfter(self.controller.auto_data_request, action, epoch)
                except Exception:
                    self.status = "网络检测暂不可用，未自动开启 4G。"
                    with self.lock:
                        self.policy.reset()
            else:
                with self.lock:
                    self.policy.reset()
            self.stop.wait(15)
