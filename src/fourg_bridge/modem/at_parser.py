from __future__ import annotations

from dataclasses import dataclass, field

from fourg_bridge.models import ATResponse

_FINALS = ("OK", "ERROR", "+CME ERROR:", "+CMS ERROR:")
_URC_PREFIXES = (
    "+CMTI:",
    "+CMT:",
    "+CREG:",
    "+CGREG:",
    "+CEREG:",
    "+QIURC:",
    "RING",
    "NO CARRIER",
)


@dataclass(slots=True)
class ATParser:
    expected_prefixes: tuple[str, ...] = ()
    _buffer: bytearray = field(default_factory=bytearray)
    _lines: list[str] = field(default_factory=list)
    _urcs: list[str] = field(default_factory=list)
    _prompt: bool = False

    def feed(self, data: bytes) -> ATResponse | None:
        self._buffer.extend(data)
        if b"> " in self._buffer:
            before, _, after = self._buffer.partition(b"> ")
            self._consume_lines(bytes(before))
            self._buffer = bytearray(after)
            self._prompt = True
            return ATResponse(tuple(self._lines), ">", bytes(before) + b"> ")

        while b"\n" in self._buffer:
            raw_line, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if self._is_urc(line):
                self._urcs.append(line)
                continue
            if self._is_final(line):
                response = ATResponse(tuple(self._lines), line, b"")
                self._lines.clear()
                self._prompt = False
                return response
            self._lines.append(line)
        return None

    def drain_urcs(self) -> tuple[str, ...]:
        urcs = tuple(self._urcs)
        self._urcs.clear()
        return urcs

    def reset_transaction(self) -> None:
        self._lines.clear()
        self._prompt = False

    def _consume_lines(self, raw: bytes) -> None:
        for item in raw.replace(b"\r", b"").split(b"\n"):
            line = item.decode("utf-8", errors="replace").strip()
            if line:
                (self._urcs if self._is_urc(line) else self._lines).append(line)

    def _is_urc(self, line: str) -> bool:
        return not line.startswith(self.expected_prefixes) and line.startswith(_URC_PREFIXES)

    @staticmethod
    def _is_final(line: str) -> bool:
        return line in _FINALS or line.startswith(("+CME ERROR:", "+CMS ERROR:"))


def parse_csq(lines: tuple[str, ...]) -> tuple[int | None, int | None]:
    for line in lines:
        if line.startswith("+CSQ:"):
            try:
                value = int(line.split(":", 1)[1].split(",", 1)[0].strip())
            except ValueError:
                return None, None
            if value == 99 or not 0 <= value <= 31:
                return value, None
            return value, -113 + 2 * value
    return None, None


def parse_registration(lines: tuple[str, ...]) -> int | None:
    for line in lines:
        if line.startswith(("+CEREG:", "+CGREG:", "+CREG:")):
            values = [value.strip() for value in line.split(":", 1)[1].split(",")]
            candidate = values[1] if len(values) > 1 else values[0]
            try:
                return int(candidate)
            except ValueError:
                return None
    return None
