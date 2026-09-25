from datetime import datetime

import pytest

from fourg_bridge.models import RawSMSPart
from fourg_bridge.sms.assembler import SMSAssembler
from fourg_bridge.sms.pdu_decoder import PDUDecodeError, decode_pdu


def _semi(value: str) -> bytes:
    padded = value + ("F" if len(value) % 2 else "")
    return bytes(int(padded[index + 1] + padded[index], 16) for index in range(0, len(padded), 2))


def _ucs2_pdu(text: str, *, udh: bytes = b"", sender: str = "10086") -> str:
    first = 0x44 if udh else 0x04
    payload = udh + text.encode("utf-16-be")
    scts = bytes.fromhex("62903251820000")  # 2026-09-23 15:28:00 +00
    pdu = (
        b"\x00"
        + bytes([first, len(sender), 0x91])
        + _semi(sender)
        + b"\x00\x08"
        + scts
        + bytes([len(payload)])
        + payload
    )
    return pdu.hex().upper()


def _gsm7_multipart_pdu(text: str, *, sequence: int) -> str:
    udh = bytes([0x05, 0x00, 0x03, 0x7A, 0x02, sequence])
    header_septets = (len(udh) * 8 + 6) // 7
    bit_offset = header_septets * 7
    packed = bytearray((bit_offset + len(text) * 7 + 7) // 8)
    packed[: len(udh)] = udh
    for index, code in enumerate(text.encode("ascii")):
        start = bit_offset + index * 7
        byte_index, shift = divmod(start, 8)
        packed[byte_index] |= (code << shift) & 0xFF
        if shift > 1:
            packed[byte_index + 1] |= code >> (8 - shift)
    sender = "10086"
    scts = bytes.fromhex("62903251820000")
    pdu = (
        b"\x00"
        + bytes([0x44, len(sender), 0x91])
        + _semi(sender)
        + b"\x00\x00"
        + scts
        + bytes([header_septets + len(text)])
        + packed
    )
    return pdu.hex().upper()


def test_unicode_and_emoji_pdu() -> None:
    part = decode_pdu(RawSMSPart("ME", 1, _ucs2_pdu("套餐剩余18GB 📶")))
    assert part.sender == "+10086"
    assert part.text == "套餐剩余18GB 📶"
    assert part.timestamp == datetime.fromisoformat("2026-09-23T15:28:00+00:00")


def test_multipart_out_of_order_and_duplicate() -> None:
    first = decode_pdu(RawSMSPart("ME", 10, _ucs2_pdu("第一段", udh=bytes.fromhex("0500037A0201"))))
    second = decode_pdu(
        RawSMSPart("SM", 11, _ucs2_pdu("第二段", udh=bytes.fromhex("0500037A0202")))
    )
    assembler = SMSAssembler()
    assert assembler.add(second) is None
    assert assembler.add(second) is None
    message = assembler.add(first)
    assert message is not None
    assert message.body == "第一段第二段"
    assert message.locations == (("ME", 10), ("SM", 11))


def test_16bit_concat_reference() -> None:
    part = decode_pdu(RawSMSPart("ME", 1, _ucs2_pdu("片段", udh=bytes.fromhex("06080412340201"))))
    assert (part.concat_ref, part.concat_total, part.concat_sequence) == (0x1234, 2, 1)


def test_gsm7_multipart_respects_udh_fill_bits() -> None:
    part = decode_pdu(RawSMSPart("ME", 1, _gsm7_multipart_pdu("HELLO", sequence=1)))
    assert part.text == "HELLO"
    assert (part.concat_ref, part.concat_total, part.concat_sequence) == (0x7A, 2, 1)


def test_invalid_pdu_is_rejected() -> None:
    with pytest.raises(PDUDecodeError):
        decode_pdu(RawSMSPart("ME", 1, "not-hex"))
