import pytest

from app.domain.game import undo_truncate, validate_move
from app.domain.values import (
    Color,
    MoveRejected,
    MoveRejectReason,
    UndoRejected,
    UndoRejectReason,
)


def test_valid_move_in_5x5_passes():
    # позиция [center, white]: ход 3 (чёрные), зона 5×5 — (9,9) внутри
    validate_move(moves=[(7, 7), (8, 8)], point=(9, 9), forbidden=[])  # не бросает


def test_out_of_board_rejected():
    for bad in [(-1, 0), (0, -1), (15, 0), (0, 15)]:
        with pytest.raises(MoveRejected) as e:
            validate_move(moves=[], point=bad, forbidden=[])
        assert e.value.reason is MoveRejectReason.OUT_OF_BOARD


def test_occupied_cell_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_move(moves=[(7, 7), (8, 8)], point=(8, 8), forbidden=[])
    assert e.value.reason is MoveRejectReason.OCCUPIED


def test_occupied_center_in_opening_is_occupied_not_opening_violation():
    # ход 2 (зона 3×3): клик в занятый центр → OCCUPIED раньше, чем проверка зоны
    with pytest.raises(MoveRejected) as e:
        validate_move(moves=[(7, 7)], point=(7, 7), forbidden=[])
    assert e.value.reason is MoveRejectReason.OCCUPIED


def test_opening_violation_move_two_outside_3x3():
    # ход 2 (зона 3×3): (5,7) вне квадрата
    with pytest.raises(MoveRejected) as e:
        validate_move(moves=[(7, 7)], point=(5, 7), forbidden=[])
    assert e.value.reason is MoveRejectReason.OPENING_VIOLATION


def test_opening_violation_move_three_outside_5x5():
    # ход 3 (зона 5×5): (10,7) вне квадрата
    with pytest.raises(MoveRejected) as e:
        validate_move(moves=[(7, 7), (8, 8)], point=(10, 7), forbidden=[])
    assert e.value.reason is MoveRejectReason.OPENING_VIOLATION


def test_inside_3x3_passes():
    validate_move(moves=[(7, 7)], point=(8, 8), forbidden=[])  # не бросает


def test_forbidden_point_rejected_for_black():
    # len=2 → ход чёрных; (9,9) внутри 5×5, но в forbidden → FORBIDDEN
    with pytest.raises(MoveRejected) as e:
        validate_move(moves=[(7, 7), (8, 8)], point=(9, 9), forbidden=[(9, 9)])
    assert e.value.reason is MoveRejectReason.FORBIDDEN


def test_forbidden_ignored_for_white():
    # len=1 → ход белых; forbidden к белым не применяется
    validate_move(moves=[(7, 7)], point=(8, 8), forbidden=[(8, 8)])  # не бросает


# rj-8sc — статус-машина этапа 2: проверка очереди снята с доменного правила
# (validate_move не знает про статус/роль). Вернуть вместе со статус-машиной.
# def test_not_your_turn_rejected_by_color(): ...
# def test_engine_thinking_rejected(): ...


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
