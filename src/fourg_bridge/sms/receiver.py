from __future__ import annotations

import hashlib
import re
from enum import StrEnum

from fourg_bridge.models import AssembledSMS, CleanupProof, RawSMSPart
from fourg_bridge.modem.at_transport import ATTransport
from fourg_bridge.storage.identity import IdentityStore

_CMGL_RE = re.compile(r'^\+CMGL:\s*(\d+),[^,]*(?:,"[^"]*")*,?(\d+)?')


class CleanupResult(StrEnum):
    DELETED = "deleted"
    PENDING = "pending"
    BLOCKED = "blocked"


class SMSReceiver:
    def __init__(
        self,
        transport: ATTransport,
        stores: tuple[str, ...] = ("ME", "SM"),
        identity: IdentityStore | None = None,
    ) -> None:
        self._transport = transport
        self._stores = stores
        self._identity_store = identity
        self.identity: str | None = None
        self.sim_key: str | None = None

    def read_identity(self) -> str | None:
        if self._identity_store is None:
            return None
        self.sim_key = None
        ready = self._transport.transact("AT+CPIN?", timeout=2)
        if not ready.ok or "+CPIN: READY" not in ready.lines:
            return None
        sim = self._transport.transact("AT+QCCID", timeout=2)
        device = self._transport.transact("AT+GSN", timeout=2)
        ids = re.findall(r"\b[0-9]{18,22}\b", " ".join(sim.lines)) if sim.ok else []
        devices = re.findall(r"\b[0-9]{15}\b", " ".join(device.lines)) if device.ok else []
        if len(ids) != 1:
            return None
        self.sim_key = self._identity_store.sim(ids[0])
        return self._identity_store.device_sim(ids[0], devices[0]) if len(devices) == 1 else None

    def poll(self) -> tuple[RawSMSPart, ...]:
        parts: list[RawSMSPart] = []
        self.identity = None
        before = self.read_identity()
        before_sim = self.sim_key
        self._transport.transact("AT+CMGF=0")
        for storage in self._stores:
            selected = self._transport.transact(f'AT+CPMS="{storage}"')
            if not selected.ok:
                continue
            response = self._transport.transact("AT+CMGL=4", timeout=15)
            parts.extend(self._parse_listing(storage, response.lines))
        after = self.read_identity()
        if self._identity_store and (before != after or before_sim != self.sim_key):
            return ()
        self.identity = after
        return tuple(parts)

    def proofs(self, message: AssembledSMS) -> tuple[CleanupProof, ...]:
        if not self.identity:
            return ()
        return tuple(
            CleanupProof(
                storage, index, hashlib.sha256(bytes.fromhex(pdu)).hexdigest(), self.identity
            )
            for (storage, index), pdu in zip(message.locations, message.ordered_pdus, strict=True)
        )

    @staticmethod
    def _parse_listing(storage: str, lines: tuple[str, ...]) -> tuple[RawSMSPart, ...]:
        result: list[RawSMSPart] = []
        index = 0
        while index < len(lines):
            match = _CMGL_RE.match(lines[index])
            if match and index + 1 < len(lines):
                pdu = lines[index + 1].strip()
                if pdu and all(ch in "0123456789ABCDEFabcdef" for ch in pdu):
                    result.append(RawSMSPart(storage, int(match.group(1)), pdu))
                index += 2
            else:
                index += 1
        return tuple(result)

    def delete_verified(self, proofs: tuple[CleanupProof, ...]) -> CleanupResult:
        if not proofs:
            return CleanupResult.BLOCKED
        with self._transport.transaction():
            for proof in proofs:
                if proof.storage not in self._stores or proof.index < 0:
                    return CleanupResult.BLOCKED
                if self.read_identity() != proof.identity:
                    return CleanupResult.BLOCKED
                if not self._transport.transact(f'AT+CPMS="{proof.storage}"').ok:
                    return CleanupResult.PENDING
                # A complete successful listing proves either exact content or absence.
                response = self._transport.transact("AT+CMGL=4", timeout=15)
                if not response.ok:
                    return CleanupResult.PENDING
                parts = self._parse_listing(proof.storage, response.lines)
                if sum(line.startswith("+CMGL:") for line in response.lines) != len(parts):
                    return CleanupResult.PENDING
                occupants = [part for part in parts if part.index == proof.index]
                if not occupants:
                    continue
                if (
                    len(occupants) != 1
                    or hashlib.sha256(bytes.fromhex(occupants[0].pdu)).hexdigest() != proof.pdu_hash
                ):
                    return CleanupResult.BLOCKED
                if self.read_identity() != proof.identity:
                    return CleanupResult.BLOCKED
                if not self._transport.transact(f"AT+CMGD={proof.index}").ok:
                    return CleanupResult.PENDING
        return CleanupResult.DELETED
