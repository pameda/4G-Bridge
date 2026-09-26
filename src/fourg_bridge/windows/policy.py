"""Windows policy is independently testable without privileges or hardware."""

from __future__ import annotations

from dataclasses import dataclass

from fourg_bridge.network.failover import Action, FailoverPolicy, Observation
from fourg_bridge.windows.platform import Inventory


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


class ControllerPolicy:
    def __init__(self) -> None:
        self.failover = FailoverPolicy()

    def decide(
        self,
        snapshot: Inventory,
        *,
        authorized: bool,
        budget: str,
        data_on: bool,
        wifi_online: bool | None,
    ) -> Decision:
        if budget != "ready":
            return Decision(Action.DISABLE if data_on else Action.HOLD, budget)
        modem = snapshot.modem()
        wifi = [adapter for adapter in snapshot.adapters if adapter.wifi]
        other = any(
            adapter.default and adapter.physical and not adapter.modem and not adapter.wifi
            for adapter in snapshot.adapters
        )
        observation = Observation(
            authorized,
            True,
            modem is not None,
            data_on,
            wifi_online,
            other_default=other,
            wifi_disconnected=not any(adapter.connected for adapter in wifi),
        )
        action = self.failover.decide(observation)
        return Decision(action, "wifi" if wifi_online else "takeover")
