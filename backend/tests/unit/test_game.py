import pytest

from app.domain.game import validate_human_move
from app.domain.values import Color, GameStatus, MoveRejected, MoveRejectReason


def test_valid_first_black_move_passes():
    validate_human_move(
        moves=[], human_color=Color.BLACK, status=GameStatus.AWAITING_HUMAN,
        point=(7, 7), forbidden=[],
    )  # не бросает


def test_out_of_board_rejected():
    for bad in [(-1, 0), (0, -1), (15, 0), (0, 15)]:
        with pytest.raises(MoveRejected) as e:
            validate_human_move(
                moves=[], human_color=Color.BLACK, status=GameStatus.AWAITING_HUMAN,
                point=bad, forbidden=[],
            )
        assert e.value.reason is MoveRejectReason.OUT_OF_BOARD


def test_occupied_cell_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7), (8, 8)], human_color=Color.BLACK,
            status=GameStatus.AWAITING_HUMAN, point=(8, 8), forbidden=[],
        )
    assert e.value.reason is MoveRejectReason.OCCUPIED


def test_not_your_turn_rejected_by_color():
    # один камень на доске — очередь белых; человек играет чёрными
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7)], human_color=Color.BLACK,
            status=GameStatus.AWAITING_HUMAN, point=(8, 8), forbidden=[],
        )
    assert e.value.reason is MoveRejectReason.NOT_YOUR_TURN


def test_engine_thinking_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7), (8, 8)], human_color=Color.BLACK,
            status=GameStatus.ENGINE_THINKING, point=(9, 9), forbidden=[],
        )
    assert e.value.reason is MoveRejectReason.NOT_YOUR_TURN


def test_finished_game_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7), (8, 8)], human_color=Color.BLACK,
            status=GameStatus.FINISHED_WHITE, point=(9, 9), forbidden=[],
        )
    assert e.value.reason is MoveRejectReason.GAME_FINISHED


def test_forbidden_point_rejected_for_black():
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7), (8, 8)], human_color=Color.BLACK,
            status=GameStatus.AWAITING_HUMAN, point=(9, 9), forbidden=[(9, 9)],
        )
    assert e.value.reason is MoveRejectReason.FORBIDDEN
