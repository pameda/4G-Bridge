from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fourg_bridge.models import DataState


@dataclass(frozen=True, slots=True)
class DataTransition:
    previous: DataState
    current: DataState
    protected: bool
    detail: str = ""
    code: str = ""


class NetworkServiceControl(Protocol):
    def set_enabled(self, service: str, enabled: bool) -> bool: ...

    def is_enabled(self, service: str) -> bool: ...


class AttachControl(Protocol):
    def set_attached(self, attached: bool) -> bool: ...


class DataSessionManager:
    def __init__(
        self,
        service: str,
        network: NetworkServiceControl,
        modem: AttachControl,
    ) -> None:
        self._service = service
        self._network = network
        self._modem = modem
        self._state = DataState.OFF
        self._cellular_priority = False

    @property
    def state(self) -> DataState:
        return self._state

    def set_enabled(
        self, enabled: bool, user_confirmed: bool = False, *, prefer_cellular: bool = False
    ) -> DataTransition:
        previous = self._state
        if enabled and not user_confirmed:
            return DataTransition(previous, previous, False, "user confirmation required")
        if enabled:
            self._state = DataState.ENABLING
            self._cellular_priority = prefer_cellular
            ensure_priority = getattr(
                self._network,
                "ensure_cellular_precedes" if prefer_cellular else "ensure_wifi_precedes",
                None,
            )
            try:
                priority_ready = not callable(ensure_priority) or ensure_priority(self._service)
            except Exception:
                priority_ready = False
            if not priority_ready:
                rollback = self.force_safe_off()
                return DataTransition(
                    previous,
                    rollback.current,
                    rollback.protected,
                    "网络优先级调整失败，4G 已回退。",
                )
            try:
                attached = self._modem.set_attached(True)
                service_enabled = attached and self._network.set_enabled(self._service, True)
                verified = service_enabled and self._network.is_enabled(self._service)
                ready = getattr(self._network, "wait_ready", None)
                link_ready = verified and (not callable(ready) or ready())
                verify_default = getattr(
                    self._network,
                    "verify_cellular_default" if prefer_cellular else "verify_wifi_default",
                    None,
                )
                wifi_is_default = not callable(verify_default) or verify_default()
            except Exception:
                rollback = self.force_safe_off()
                return DataTransition(
                    previous,
                    rollback.current,
                    rollback.protected,
                    "连接操作超时或失败，已尝试关闭 4G。",
                )
            if not (attached and verified and link_ready):
                rollback = self.force_safe_off()
                detail = (
                    "模块未能附着蜂窝网络，请检查 SIM 和注册状态。"
                    if not attached
                    else "macOS 未能启用 QDC507 网络服务。"
                    if not verified
                    else "QDC507 未取得有效 IP 或网关，已关闭数据。请重新插拔模块后重试。"
                )
                return DataTransition(
                    previous,
                    rollback.current,
                    rollback.protected,
                    detail,
                    "network_not_ready" if attached and verified else "enable_failed",
                )
            if attached and verified and not wifi_is_default:
                disabled = self._network.set_enabled(self._service, False)
                service_off = disabled and not self._network.is_enabled(self._service)
                detached = self._modem.set_attached(False)
                self._state = (
                    DataState.OFF if service_off and detached else DataState.PROTECTION_FAILED
                )
                self._restore_priority()
                return DataTransition(
                    previous,
                    self._state,
                    self._state == DataState.OFF,
                    "预期网络未成为默认接口，4G 已回退。",
                )
            self._state = (
                DataState.ON
                if attached and verified and wifi_is_default
                else DataState.PROTECTION_FAILED
            )
            detail = "data enabled" if verified else "enable failed"
            return DataTransition(previous, self._state, verified, detail)

        self._state = DataState.DISABLING
        try:
            disabled = self._network.set_enabled(self._service, False)
            verified = disabled and not self._network.is_enabled(self._service)
        except Exception:
            verified = False
        if verified:
            self._state = DataState.OFF
            restored = self._restore_priority()
            return DataTransition(
                previous,
                self._state,
                True,
                "network service disabled" if restored else "数据已关闭；Wi-Fi 优先级恢复失败。",
            )
        try:
            detached = self._modem.set_attached(False)
        except Exception:
            detached = False
        self._state = DataState.OFF if detached else DataState.PROTECTION_FAILED
        self._restore_priority()
        return DataTransition(
            previous,
            self._state,
            detached,
            "network service disable failed; modem detach fallback used",
        )

    def force_safe_off(self) -> DataTransition:
        return self.set_enabled(False, user_confirmed=False)

    def _restore_priority(self) -> bool:
        if not self._cellular_priority:
            return True
        restore = getattr(self._network, "ensure_wifi_precedes", None)
        try:
            if callable(restore) and restore(self._service):
                self._cellular_priority = False
                return True
        except Exception:
            pass
        return False
