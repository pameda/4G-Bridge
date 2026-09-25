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

    @property
    def state(self) -> DataState:
        return self._state

    def set_enabled(self, enabled: bool, user_confirmed: bool = False) -> DataTransition:
        previous = self._state
        if enabled and not user_confirmed:
            return DataTransition(previous, previous, False, "user confirmation required")
        if enabled:
            self._state = DataState.ENABLING
            attached = self._modem.set_attached(True)
            service_enabled = self._network.set_enabled(self._service, True)
            verified = service_enabled and self._network.is_enabled(self._service)
            self._state = DataState.ON if attached and verified else DataState.PROTECTION_FAILED
            detail = "data enabled" if verified else "enable failed"
            return DataTransition(previous, self._state, verified, detail)

        self._state = DataState.DISABLING
        disabled = self._network.set_enabled(self._service, False)
        verified = disabled and not self._network.is_enabled(self._service)
        if verified:
            self._state = DataState.OFF
            return DataTransition(previous, self._state, True, "network service disabled")
        detached = self._modem.set_attached(False)
        self._state = DataState.OFF if detached else DataState.PROTECTION_FAILED
        return DataTransition(
            previous,
            self._state,
            detached,
            "network service disable failed; modem detach fallback used",
        )

    def force_safe_off(self) -> DataTransition:
        return self.set_enabled(False, user_confirmed=False)
