import pytest

from app.domain.game import undo_truncate, validate_human_move
from app.domain.values import (
    Color,
    GameStatus,
    MoveRejected,
    MoveRejectReason,
    UndoRejected,
    UndoRejectReason,
)


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


def test_undo_black_human_removes_engine_and_own_move():
    # чёрный человек: [B(7,7), W(8,8)] → снова ход чёрных, убрать оба
    assert undo_truncate(moves=[(7, 7), (8, 8)], human_color=Color.BLACK) == []


def test_undo_black_human_after_own_finishing_move_removes_one():
    # партия закончилась ходом чёрного человека (нечётная длина) → убрать один
    moves = [(7, 7), (8, 8), (7, 8)]
    assert undo_truncate(moves=moves, human_color=Color.BLACK) == [(7, 7), (8, 8)]


def test_undo_white_human_removes_engine_and_own_move():
    # белый человек: [B, W, B] → очередь белых после усечения до 1 камня
    moves = [(7, 7), (8, 8), (9, 9)]
    assert undo_truncate(moves=moves, human_color=Color.WHITE) == [(7, 7)]


def test_undo_white_human_after_own_finishing_move_removes_one():
    moves = [(7, 7), (8, 8), (9, 9), (8, 9)]
    assert undo_truncate(moves=moves, human_color=Color.WHITE) == [(7, 7), (8, 8), (9, 9)]


def test_undo_black_human_with_empty_board_rejected():
    with pytest.raises(UndoRejected) as e:
        undo_truncate(moves=[], human_color=Color.BLACK)
    assert e.value.reason is UndoRejectReason.NOTHING_TO_UNDO


def test_undo_white_human_with_only_engine_move_rejected():
    # у белого человека ещё нет своих ходов — откатывать нечего
    with pytest.raises(UndoRejected) as e:
        undo_truncate(moves=[(7, 7)], human_color=Color.WHITE)
    assert e.value.reason is UndoRejectReason.NOTHING_TO_UNDO
