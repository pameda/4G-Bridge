"""Installation-local, domain-separated fingerprints; raw identifiers never persist."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path


class IdentityStore:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / "identity.key"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
        self._secret = path.read_bytes()
        if len(self._secret) != 32:
            raise ValueError("identity key unavailable")

    def sim(self, iccid: str | None) -> str | None:
        if not iccid or not re.fullmatch(r"[0-9]{18,22}", iccid):
            return None
        return self._digest("sim", iccid)

    def device_sim(self, iccid: str, imei: str) -> str | None:
        if not self.sim(iccid) or not re.fullmatch(r"[0-9]{15}", imei):
            return None
        return self._digest("cleanup", iccid + ":" + imei)

    def _digest(self, purpose: str, value: str) -> str:
        return hmac.new(self._secret, (purpose + ":" + value).encode(), hashlib.sha256).hexdigest()
