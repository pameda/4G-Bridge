"""TLS-verified probes pinned to the Wi-Fi egress interface, not just its IP."""

from __future__ import annotations

import http.client
import socket
import ssl


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
