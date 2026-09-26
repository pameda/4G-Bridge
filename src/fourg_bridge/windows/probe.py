"""TLS-verified probes pinned to the Wi-Fi egress interface, not just its IP."""

from __future__ import annotations

import http.client
import multiprocessing
import socket
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection


class BoundHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, index: int, address: str) -> None:
        self.tls_context = ssl.create_default_context()
        super().__init__(host, timeout=2, context=self.tls_context)
        self.index, self.address = index, address

    def connect(self) -> None:
        addresses = socket.getaddrinfo(self.host, 443, socket.AF_INET, socket.SOCK_STREAM)
        if not addresses:
            raise OSError("probe DNS unavailable")
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            raw.settimeout(2)
            # Windows IP_UNICAST_IF is 31; its IF_INDEX must be network byte order.
            # A source-address-only bind can follow the wrong route on a multihomed host.
            raw.setsockopt(socket.IPPROTO_IP, 31, socket.htonl(self.index))
            raw.bind((self.address, 0))
            raw.connect(addresses[0][4])
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def online(index: int, address: str) -> bool:
    for host, path, expected in (
        ("www.msftconnecttest.com", "/connecttest.txt", b"Microsoft Connect Test"),
        ("captive.apple.com", "/hotspot-detect.html", b"<BODY>Success</BODY>"),
    ):
        connection = BoundHTTPS(host, index, address)
        try:
            connection.request("GET", path, headers={"Connection": "close"})
            response = connection.getresponse()
            body = response.read(4097)
            if response.status == 200 and len(body) <= 4096 and expected in body:
                return True
        except (OSError, http.client.HTTPException):
            continue
        finally:
            connection.close()
    return False


@dataclass(frozen=True)
class ProbeResult:
    state: str

    @property
    def online(self) -> bool | None:
        return (
            True
            if self.state == "online"
            else False
            if self.state in {"offline", "timeout"}
            else None
        )


def _probe_worker(pipe: Connection, interfaces: tuple[tuple[int, str], ...]) -> None:
    try:
        pipe.send(
            "online" if any(online(index, address) for index, address in interfaces) else "offline"
        )
    except Exception:
        pipe.send("error")
    finally:
        pipe.close()


class ProbeRunner:
    """DNS/TLS/HTTP share a deadline; terminate isolated worker on timeout/cancel."""

    def __init__(self, timeout: float = 6.0) -> None:
        self.timeout = timeout
        self._lock = threading.Lock()

    def run(
        self,
        interfaces: tuple[tuple[int, str], ...],
        cancelled: Callable[[], bool],
        *,
        worker: Callable[[Connection, tuple[tuple[int, str], ...]], None] = _probe_worker,
    ) -> ProbeResult:
        if not self._lock.acquire(blocking=False):
            return ProbeResult("error")
        process = None
        receiver = sender = None
        try:
            if cancelled():
                return ProbeResult("cancelled")
            context = multiprocessing.get_context("spawn")
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(target=worker, args=(sender, interfaces), daemon=True)
            deadline = time.monotonic() + self.timeout
            process.start()
            sender.close()
            while time.monotonic() < deadline:
                if cancelled():
                    return ProbeResult("cancelled")
                if receiver.poll(min(0.05, max(0, deadline - time.monotonic()))):
                    result = receiver.recv()
                    return ProbeResult(
                        result if result in {"online", "offline", "error"} else "error"
                    )
                if not process.is_alive():
                    return ProbeResult("error")
            return ProbeResult("timeout")
        except (OSError, EOFError, ValueError):
            return ProbeResult("error")
        finally:
            if process and process.pid:
                if process.is_alive():
                    process.terminate()
                process.join(0.5)
                if process.is_alive():
                    process.kill()
                    process.join(0.5)
                if not process.is_alive():
                    process.close()
            if receiver:
                receiver.close()
            if sender:
                sender.close()
            self._lock.release()


def _smoke_worker(pipe: Connection, interfaces: tuple[tuple[int, str], ...]) -> None:
    if interfaces:
        time.sleep(60)  # Synthetic stuck resolver; never connects to any network.
    pipe.send("online")
    pipe.close()


def probe_self_test() -> bool:
    success = ProbeRunner().run((), lambda: False, worker=_smoke_worker)
    started = time.monotonic()
    timeout = ProbeRunner(0.2).run(((0, ""),), lambda: False, worker=_smoke_worker)
    return (
        success.state == "online"
        and timeout.state == "timeout"
        and time.monotonic() - started < 2.2
    )
