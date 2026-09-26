"""Only nonsensitive preferences; data-on and 80% consent are never persisted."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Preferences:
    auto_takeover: bool = False
    theme: str = "system"

    @classmethod
    def load(cls, path: Path) -> Preferences:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                data.get("auto_takeover") is True,
                data.get("theme") if data.get("theme") in ("light", "dark") else "system",
            )
        except (OSError, ValueError, AttributeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(asdict(self), stream)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)


def app_directory() -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Windows app data only")
    return Path(os.environ["LOCALAPPDATA"]) / "4G Bridge"


def login_enabled() -> bool:
    winreg = importlib.import_module("winreg")

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "4G Bridge")
            return bool(value == subprocess.list2cmdline([sys.executable, "--background"]))
    except OSError:
        return False


def set_login(enabled: bool) -> None:
    winreg = importlib.import_module("winreg")

    if not getattr(sys, "frozen", False):
        raise RuntimeError("请使用安装后的应用设置登录启动")
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                "4G Bridge",
                0,
                winreg.REG_SZ,
                subprocess.list2cmdline([sys.executable, "--background"]),
            )
        else:
            with suppress(FileNotFoundError):
                winreg.DeleteValue(key, "4G Bridge")
