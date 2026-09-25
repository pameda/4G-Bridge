from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fourg_bridge.models import AssembledSMS, DecodedSMSPart


@dataclass(slots=True)
class _Assembly:
    created_at: datetime
    total: int
    parts: dict[int, DecodedSMSPart] = field(default_factory=dict)


class SMSAssembler:
    def __init__(self, expiry: timedelta = timedelta(hours=24)) -> None:
        self._expiry = expiry
        self._assemblies: dict[tuple[str, int, str], _Assembly] = {}

    def add(self, part: DecodedSMSPart) -> AssembledSMS | None:
        self._expire()
        if part.concat_ref is None or part.concat_total <= 1:
            return self._assemble((part,))
        date_key = part.timestamp.astimezone(UTC).strftime("%Y%m%d")
        key = (part.sender, part.concat_ref, date_key)
        assembly = self._assemblies.setdefault(key, _Assembly(datetime.now(UTC), part.concat_total))
        if assembly.total != part.concat_total:
            self._assemblies.pop(key, None)
            assembly = _Assembly(datetime.now(UTC), part.concat_total)
            self._assemblies[key] = assembly
        assembly.parts.setdefault(part.concat_sequence, part)
        expected = set(range(1, assembly.total + 1))
        if set(assembly.parts) != expected:
            return None
        ordered = tuple(assembly.parts[index] for index in sorted(assembly.parts))
        self._assemblies.pop(key, None)
        return self._assemble(ordered)

    def _expire(self) -> None:
        cutoff = datetime.now(UTC) - self._expiry
        expired = [key for key, value in self._assemblies.items() if value.created_at < cutoff]
        for key in expired:
            self._assemblies.pop(key, None)

    @staticmethod
    def _assemble(parts: tuple[DecodedSMSPart, ...]) -> AssembledSMS:
        first = parts[0]
        return AssembledSMS(
            sender=first.sender,
            timestamp=first.timestamp,
            body="".join(part.text for part in parts),
            ordered_pdus=tuple(part.raw_pdu for part in parts),
            locations=tuple((part.storage, part.index) for part in parts),
        )
