import pytest

from app.rapfi.protocol import LineKind, ProtocolError, parse_line


def test_parse_ok():
    assert parse_line("OK").kind is LineKind.OK


def test_parse_move():
    parsed = parse_line("5,4")
    assert parsed.kind is LineKind.MOVE
    assert parsed.move == (5, 4)


def test_parse_move_two_digit_coords():
    assert parse_line("14,10").move == (14, 10)


def test_move_out_of_board_is_protocol_error():
    with pytest.raises(ProtocolError):
        parse_line("15,0")


def test_parse_noise_lines():
    for raw in [
        "MESSAGE Speed 408K | Depth 7-9 | Eval -66 | Node 817 | Time 2ms",
        "MESSAGE mix9svq nnue: load weight from engine/rapfi/Networks/...",
        "DEBUG something",
        "INFO whatever",
        'name="Rapfi", version="0.43.02", author="Rapfi developers", country="China"',
        "",
    ]:
        assert parse_line(raw).kind is LineKind.NOISE, raw


def test_parse_error_line():
    parsed = parse_line("ERROR Unknown command: FOOBAR")
    assert parsed.kind is LineKind.ERROR
    assert "FOOBAR" in parsed.text


def test_parse_forbid_single():
    parsed = parse_line("FORBID 0707.")
    assert parsed.kind is LineKind.FORBID
    assert parsed.forbidden == ((7, 7),)


def test_parse_forbid_multiple_and_two_digit():
    parsed = parse_line("FORBID 07071412.")
    assert parsed.forbidden == ((7, 7), (14, 12))


def test_parse_forbid_empty():
    parsed = parse_line("FORBID .")
    assert parsed.kind is LineKind.FORBID
    assert parsed.forbidden == ()


def test_parse_forbid_malformed_is_protocol_error():
    with pytest.raises(ProtocolError):
        parse_line("FORBID 077.")  # нечётное число цифр — битая склейка
