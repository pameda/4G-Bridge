from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    relay_enabled: bool = True
    poll_interval_seconds: int = 20
    appearance: str = "system"
    auto_data_enabled: bool = False
    data_limit_bytes: int = 0
    data_budget_period: str = "allowance"
    carrier_policy_enabled: bool = False


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Settings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            appearance = payload.get("appearance", "system")
            return Settings(
                relay_enabled=payload.get("relay_enabled", True) is True,
                poll_interval_seconds=max(10, int(payload.get("poll_interval_seconds", 20))),
                appearance=appearance if appearance in ("system", "light", "dark") else "system",
                auto_data_enabled=payload.get("auto_data_enabled") is True,
                carrier_policy_enabled=payload.get("carrier_policy_enabled") is True,
                data_limit_bytes=max(0, int(payload.get("data_limit_bytes", 0))),
                data_budget_period=(
                    "month" if payload.get("data_budget_period") == "month" else "allowance"
                ),
            )
        except FileNotFoundError:
            return Settings()
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
            # Corruption must not override a user's previously disabled relay.
            return Settings(relay_enabled=False)

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix="settings-", text=True
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(settings), handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
