"""Crash-recoverable lease affecting only the verified modem's IPv4 metric."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from fourg_bridge.windows.platform import PlatformError, adapter_metric


class MetricLease:
    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire(self, guid: str) -> None:
        guid = str(UUID(guid))
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value["guid"] != guid:
                raise PlatformError("另一模块的优先级尚未恢复，请连接原模块恢复")
        else:
            value = adapter_metric(guid)
            value["guid"] = guid
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            with temp.open("w", encoding="utf-8") as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(self.path)
        adapter_metric(guid, 1)

    def restore(self, guid: str) -> None:
        if not self.path.exists():
            return
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value["guid"] != str(UUID(guid)):
            raise PlatformError("需要连接原模块恢复优先级")
        adapter_metric(guid, int(value["metric"]), value["automatic"] is True)
        self.path.unlink()  # Only our validated, successfully restored lease record.
