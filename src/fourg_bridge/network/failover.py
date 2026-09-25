"""Pure failover policy; no network changes or implicit spending authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Action(StrEnum):
    HOLD = "hold"
    ENABLE = "enable"
    DISABLE = "disable"


@dataclass(frozen=True, slots=True)
class Observation:
    enabled: bool
    budget_available: bool
    device_available: bool
    data_on: bool
    wifi_online: bool | None
    vpn_active: bool = False
    other_default: bool = False


class FailoverPolicy:
    """Three failures before takeover, two successes before returning to Wi-Fi."""

    def __init__(self) -> None:
        self.failures = 0
        self.successes = 0
        self.owned = False
        self.paused = False

    def reset(self) -> None:
        self.failures = self.successes = 0

    def decide(self, observation: Observation) -> Action:
        if not observation.budget_available:
            self.reset()
            return Action.DISABLE if observation.data_on else Action.HOLD
        if not observation.enabled or self.paused or not observation.device_available:
            self.reset()
            return Action.DISABLE if self.owned and observation.data_on else Action.HOLD
        if observation.vpn_active or observation.other_default:
            self.reset()
            return Action.DISABLE if self.owned and observation.data_on else Action.HOLD
        if observation.wifi_online is None:
            self.reset()
            return Action.HOLD
        if observation.wifi_online:
            self.failures = 0
            self.successes += 1
            if self.owned and observation.data_on and self.successes >= 2:
                return Action.DISABLE
        else:
            self.successes = 0
            self.failures += 1
            if not observation.data_on and self.failures >= 3:
                return Action.ENABLE
        return Action.HOLD

    def completed(self, action: Action, success: bool) -> None:
        self.reset()
        if action == Action.ENABLE:
            self.owned = success
            # A failed enable never starts a reboot/retry loop.
            self.paused = not success
        elif action == Action.DISABLE and success:
            self.owned = False
