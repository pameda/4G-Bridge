from __future__ import annotations

import hashlib
import re

_PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d -]{5,}\d)(?!\w)")
_ICCID_RE = re.compile(r"(?<!\d)89\d{16,20}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def redact_identifier(value: str | None) -> str:
    if not value:
        return "—"
    clean = value.strip()
    if "@" in clean:
        name, domain = clean.split("@", 1)
        return f"{name[:1]}***@{domain[:1]}***"
    digits = "".join(ch for ch in clean if ch.isdigit())
    if len(digits) <= 4:
        return "****"
    return f"{digits[:3]}****{digits[-4:]}"


def redact_log(text: str) -> str:
    redacted = _ICCID_RE.sub("[ICCID_REDACTED]", text)
    redacted = _EMAIL_RE.sub("[APPLE_ID_REDACTED]", redacted)
    return _PHONE_RE.sub(lambda match: redact_identifier(match.group(0)), redacted)


def stable_message_hash(sender: str, timestamp: str, ordered_pdus: tuple[str, ...]) -> str:
    normalized_sender = "".join(ch for ch in sender if ch.isalnum() or ch == "+").casefold()
    material = "\x1f".join((normalized_sender, timestamp, *[p.upper() for p in ordered_pdus]))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
