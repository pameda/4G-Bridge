from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from fourg_bridge.models import ATResponse
from fourg_bridge.modem.at_parser import ATParser


class ATTransportError(RuntimeError):
    pass


class ATTimeout(ATTransportError):
    pass


@dataclass(slots=True)
class _Request:
    command: str
    payload: bytes | None
    timeout: float
    completed: threading.Event = field(default_factory=threading.Event)
    response: ATResponse | None = None
    error: BaseException | None = None


class ATTransport:
    """Owns all USB reads on one worker thread and serializes transactions."""

    def __init__(
        self,
        writer: Callable[[bytes, int], object],
        reader: Callable[[int], bytes],
        urc_handler: Callable[[str], None] | None = None,
    ) -> None:
        self._writer = writer
        self._reader = reader
        self._urc_handler = urc_handler
        self._queue: queue.Queue[_Request | None] = queue.Queue()
        self._transaction_lock = threading.RLock()
        self._thread = threading.Thread(target=self._run, name="QDC507-AT", daemon=True)
        self._thread.start()

    def transact(
        self, command: str, payload: bytes | None = None, timeout: float = 5.0
    ) -> ATResponse:
        with self._transaction_lock:
            return self._transact(command, payload, timeout)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Keep identity/read/delete sequences contiguous on this transport."""
        with self._transaction_lock:
            yield

    def _transact(self, command: str, payload: bytes | None, timeout: float) -> ATResponse:
        if not command.startswith("AT"):
            raise ValueError("AT command must begin with AT")
        request = _Request(command, payload, timeout)
        self._queue.put(request)
        if not request.completed.wait(timeout + 1):
            raise ATTimeout(f"worker timed out for {command.split('=', 1)[0]}")
        if request.error is not None:
            if isinstance(request.error, ATTimeout):
                raise request.error
            raise ATTransportError(str(request.error)) from request.error
        if request.response is None:
            raise ATTransportError("AT worker returned no response")
        return request.response

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while (request := self._queue.get()) is not None:
            try:
                request.response = self._perform(request)
            except BaseException as error:
                request.error = error
            finally:
                request.completed.set()

    def _perform(self, request: _Request) -> ATResponse:
        parser = ATParser((_response_prefix(request.command),))
        encoded = request.command.encode("ascii", errors="strict") + b"\r"
        self._writer(encoded, 1000)
        deadline = time.monotonic() + request.timeout
        payload_sent = request.payload is None
        while time.monotonic() < deadline:
            try:
                data = bytes(self._reader(250))
            except TimeoutError:
                continue
            if not data:
                continue
            response = parser.feed(data)
            for urc in parser.drain_urcs():
                if self._urc_handler:
                    self._urc_handler(urc)
            if response is None:
                continue
            if response.final == ">" and not payload_sent:
                assert request.payload is not None
                self._writer(request.payload + b"\x1a", 1000)
                payload_sent = True
                parser.reset_transaction()
                continue
            return response
        raise ATTimeout(f"timeout waiting for {request.command.split('=', 1)[0]}")


def _response_prefix(command: str) -> str:
    if not command.startswith("AT+"):
        return "\0"
    name = command[3:].split("=", 1)[0].split("?", 1)[0]
    return f"+{name}:"
