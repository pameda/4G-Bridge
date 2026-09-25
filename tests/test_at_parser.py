from fourg_bridge.modem.at_parser import ATParser, parse_csq, parse_registration


def test_fragmented_response_and_urc() -> None:
    parser = ATParser()
    assert parser.feed(b"\r\n+CS") is None
    response = parser.feed(b'Q: 18,99\r\n+CMTI: "ME",3\r\nOK\r\n')
    assert response is not None
    assert response.ok
    assert response.lines == ("+CSQ: 18,99",)
    assert parser.drain_urcs() == ('+CMTI: "ME",3',)


def test_prompt_and_error() -> None:
    parser = ATParser()
    prompt = parser.feed(b"\r\n> ")
    assert prompt is not None and prompt.final == ">"
    parser.reset_transaction()
    error = parser.feed(b"\r\n+CMS ERROR: 500\r\n")
    assert error is not None and not error.ok


def test_signal_and_registration_parsers() -> None:
    assert parse_csq(("+CSQ: 18,99",)) == (18, -77)
    assert parse_csq(("+CSQ: 99,99",)) == (99, None)
    assert parse_csq(("broken",)) == (None, None)
    assert parse_registration(("+CEREG: 0,5",)) == 5
    assert parse_registration(("+CREG: 1",)) == 1


def test_expected_registration_response_is_not_classified_as_urc() -> None:
    parser = ATParser(("+CEREG:",))
    response = parser.feed(b"\r\n+CEREG: 0,5\r\nOK\r\n")
    assert response is not None
    assert response.lines == ("+CEREG: 0,5",)
    assert parser.drain_urcs() == ()
