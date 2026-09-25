from fourg_bridge.support.privacy import redact_identifier, redact_log, stable_message_hash


def test_log_redaction() -> None:
    text = "sender 15555550123 iccid 89860123456789012345 user@example.com"
    redacted = redact_log(text)
    assert "15555550123" not in redacted
    assert "89860123456789012345" not in redacted
    assert "user@example.com" not in redacted
    assert redact_identifier("15555550123") == "155****0123"


def test_stable_hash_normalizes_sender_and_pdu_case() -> None:
    left = stable_message_hash("+1 555-555-0123", "2026", ("aabb",))
    right = stable_message_hash("+15555550123", "2026", ("AABB",))
    assert left == right
    assert len(left) == 64
