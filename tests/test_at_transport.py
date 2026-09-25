import queue

import pytest

from fourg_bridge.modem.at_transport import ATTimeout, ATTransport


class USB:
    def __init__(self, responses):
        self.responses = queue.Queue()
        for response in responses:
            self.responses.put(response)
        self.writes = []

    def write(self, data, timeout):
        self.writes.append(bytes(data))

    def read(self, timeout):
        try:
            return self.responses.get_nowait()
        except queue.Empty as error:
            raise TimeoutError from error


def test_worker_serializes_response_and_urc() -> None:
    usb = USB([b'\r\n+CMTI: "ME",1\r\n+CSQ: 18,99\r\nOK\r\n'])
    urcs = []
    transport = ATTransport(usb.write, usb.read, urcs.append)
    response = transport.transact("AT+CSQ", timeout=1)
    transport.close()
    assert response.lines == ("+CSQ: 18,99",)
    assert usb.writes == [b"AT+CSQ\r"]
    assert urcs == ['+CMTI: "ME",1']


def test_payload_is_sent_only_after_prompt() -> None:
    usb = USB([b"> ", b"\r\nOK\r\n"])
    transport = ATTransport(usb.write, usb.read)
    assert transport.transact("AT+CMGS=10", b"AABB", timeout=1).ok
    transport.close()
    assert usb.writes == [b"AT+CMGS=10\r", b"AABB\x1a"]


def test_registration_query_keeps_response_and_dispatches_other_urc() -> None:
    usb = USB([b'\r\n+CMTI: "ME",1\r\n+CEREG: 0,5\r\nOK\r\n'])
    urcs = []
    transport = ATTransport(usb.write, usb.read, urcs.append)
    response = transport.transact("AT+CEREG?", timeout=1)
    transport.close()
    assert response.lines == ("+CEREG: 0,5",)
    assert urcs == ['+CMTI: "ME",1']


def test_timeout_and_invalid_command() -> None:
    usb = USB([])
    transport = ATTransport(usb.write, usb.read)
    with pytest.raises(ValueError):
        transport.transact("NOPE")
    with pytest.raises(ATTimeout):
        transport.transact("AT", timeout=0.01)
    transport.close()
