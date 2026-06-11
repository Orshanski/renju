import pytest

from app.domain.engine_params import EngineParams
from app.rapfi.protocol import (
    LineKind,
    ProtocolError,
    block_commands,
    forbid_commands,
    init_commands,
    parse_line,
    position_commands,
)


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


def test_init_commands():
    params = EngineParams(strength=55, timeout_turn_ms=2500)
    assert init_commands(params) == [
        "START 15",
        "INFO rule 4",
        "INFO strength 55",
        "INFO timeout_turn 2500",
    ]


def test_position_commands_empty_board_is_begin():
    assert position_commands([]) == ["BEGIN"]


def test_position_commands_engine_moves_second():
    # человек-чёрный сходил (7,7); очередь движка (белые): who=2 у чужого камня
    assert position_commands([(7, 7)]) == ["BOARD", "7,7,2", "DONE"]


def test_position_commands_engine_is_black():
    # движок-чёрный (7,7) who=1, человек-белый (8,8) who=2
    assert position_commands([(7, 7), (8, 8)]) == ["BOARD", "7,7,1", "8,8,2", "DONE"]


def test_forbid_commands():
    assert forbid_commands([(8, 7), (0, 0)]) == [
        "YXBOARD",
        "8,7,1",
        "0,0,2",
        "DONE",
        "YXSHOWFORBID",
    ]


def test_position_commands_rejects_non_int_coordinates():
    for bad in [(7.0, 7), ("7", 7), (7, None), (True, 3)]:
        with pytest.raises(ProtocolError):
            position_commands([bad])  # type: ignore[list-item]


def test_position_commands_rejects_out_of_board_and_duplicates():
    with pytest.raises(ProtocolError):
        position_commands([(15, 0)])
    with pytest.raises(ProtocolError):
        position_commands([(-1, 3)])
    with pytest.raises(ProtocolError):
        position_commands([(7, 7), (7, 7)])


def test_block_commands_format():
    assert block_commands([(8, 7), (0, 0)]) == ["YXBLOCK", "8,7", "0,0", "DONE"]


def test_block_commands_empty_is_empty_list():
    assert block_commands([]) == []


def test_block_commands_rejects_non_int_and_out_of_board():
    # pytest и ProtocolError уже импортированы в шапке test_protocol.py
    for bad in [(7.0, 7), (True, 3), (15, 0), (-1, 3)]:
        with pytest.raises(ProtocolError):
            block_commands([bad])  # type: ignore[list-item]
