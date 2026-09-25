from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fourg_bridge.models import DecodedSMSPart, RawSMSPart

_GSM7 = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./"
    "0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = {
    0x0A: "\f",
    0x14: "^",
    0x28: "{",
    0x29: "}",
    0x2F: "\\",
    0x3C: "[",
    0x3D: "~",
    0x3E: "]",
    0x40: "|",
    0x65: "€",
}


class PDUDecodeError(ValueError):
    pass


def decode_pdu(raw: RawSMSPart) -> DecodedSMSPart:
    try:
        data = bytes.fromhex("".join(raw.pdu.split()))
    except ValueError as error:
        raise PDUDecodeError("PDU is not hexadecimal") from error
    if len(data) < 2:
        raise PDUDecodeError("PDU is too short")
    cursor = 1 + data[0]
    if cursor + 2 >= len(data):
        raise PDUDecodeError("invalid SMSC length")

    first_octet = data[cursor]
    cursor += 1
    udhi = bool(first_octet & 0x40)
    sender_digits = data[cursor]
    cursor += 1
    sender_type = data[cursor]
    cursor += 1
    sender_octets = (sender_digits + 1) // 2
    if cursor + sender_octets + 10 > len(data):
        raise PDUDecodeError("truncated sender or header")
    sender = _decode_address(data[cursor : cursor + sender_octets], sender_digits, sender_type)
    cursor += sender_octets
    cursor += 1  # protocol identifier
    dcs = data[cursor]
    cursor += 1
    timestamp = _decode_timestamp(data[cursor : cursor + 7])
    cursor += 7
    udl = data[cursor]
    cursor += 1
    user_data = data[cursor:]

    concat_ref: int | None = None
    concat_total = 1
    concat_sequence = 1
    header_octets = 0
    if udhi:
        if not user_data:
            raise PDUDecodeError("UDHI set without user data")
        header_octets = user_data[0] + 1
        if header_octets > len(user_data):
            raise PDUDecodeError("truncated UDH")
        concat_ref, concat_total, concat_sequence = _parse_udh(user_data[1:header_octets])

    alphabet = dcs & 0x0C
    if alphabet == 0x08:
        payload = user_data[header_octets:udl]
        try:
            text = payload.decode("utf-16-be")
        except UnicodeDecodeError as error:
            raise PDUDecodeError("invalid UCS-2/UTF-16BE payload") from error
    elif alphabet == 0x04:
        text = user_data[header_octets:udl].decode("latin-1")
    else:
        header_septets = (header_octets * 8 + 6) // 7
        text_septets = max(0, udl - header_septets)
        # A GSM 7-bit UDH is padded to the next septet boundary.  Starting at
        # the raw octet boundary would treat that fill bit as message data.
        text = _decode_gsm7(user_data, text_septets, header_septets * 7)

    return DecodedSMSPart(
        sender=sender,
        timestamp=timestamp,
        text=text,
        raw_pdu=raw.pdu.upper(),
        storage=raw.storage,
        index=raw.index,
        concat_ref=concat_ref,
        concat_total=concat_total,
        concat_sequence=concat_sequence,
    )


def _decode_address(data: bytes, digits: int, address_type: int) -> str:
    value = _decode_semi_octets(data)[:digits]
    return f"+{value}" if address_type & 0x70 == 0x10 and not value.startswith("+") else value


def _decode_semi_octets(data: bytes) -> str:
    result = ""
    for value in data:
        result += f"{value & 0x0F:X}{value >> 4:X}"
    return result.rstrip("F")


def _decode_timestamp(data: bytes) -> datetime:
    if len(data) != 7:
        raise PDUDecodeError("invalid SCTS")
    values = [int(_decode_semi_octets(bytes([item]))) for item in data[:6]]
    year = 2000 + values[0] if values[0] < 90 else 1900 + values[0]
    raw_tz = data[6]
    negative = bool(raw_tz & 0x08)
    tz_byte = raw_tz & 0xF7
    quarter_hours = int(_decode_semi_octets(bytes([tz_byte])))
    offset = timedelta(minutes=15 * quarter_hours * (-1 if negative else 1))
    try:
        month, day, hour, minute, second = values[1:]
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone(offset))
    except ValueError as error:
        raise PDUDecodeError("invalid SCTS date") from error


def _parse_udh(header: bytes) -> tuple[int | None, int, int]:
    cursor = 0
    while cursor + 2 <= len(header):
        identifier = header[cursor]
        length = header[cursor + 1]
        value = header[cursor + 2 : cursor + 2 + length]
        if len(value) != length:
            break
        if identifier == 0x00 and length == 3:
            return value[0], value[1], value[2]
        if identifier == 0x08 and length == 4:
            return int.from_bytes(value[:2]), value[2], value[3]
        cursor += 2 + length
    return None, 1, 1


def _decode_gsm7(data: bytes, septet_count: int, bit_offset: int = 0) -> str:
    codes: list[int] = []
    for index in range(septet_count):
        start = bit_offset + index * 7
        byte_index = start // 8
        shift = start % 8
        if byte_index >= len(data):
            break
        value = data[byte_index] >> shift
        if shift > 1 and byte_index + 1 < len(data):
            value |= data[byte_index + 1] << (8 - shift)
        codes.append(value & 0x7F)

    result: list[str] = []
    escaped = False
    for code in codes:
        if escaped:
            result.append(_GSM7_EXT.get(code, "�"))
            escaped = False
        elif code == 0x1B:
            escaped = True
        else:
            result.append(_GSM7[code] if code < len(_GSM7) else "�")
    if escaped:
        result.append("�")
    return "".join(result)
