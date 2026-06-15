import pytest

from app.domain.errors import MoveRejected, MoveRejectReason, UndoRejected, UndoRejectReason
from app.domain.game import undo_truncate, validate_move
from app.domain.values import Color


def test_valid_move_passes():
    validate_move(moves=[(7, 7), (8, 8)], point=(9, 9))  # целостность ок → не бросает


def test_out_of_board_rejected():
    for bad in [(-1, 0), (0, -1), (15, 0), (0, 15)]:
        with pytest.raises(MoveRejected) as e:
            validate_move(moves=[], point=bad)
        assert e.value.reason is MoveRejectReason.OUT_OF_BOARD


def test_occupied_cell_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_move(moves=[(7, 7), (8, 8)], point=(8, 8))
    assert e.value.reason is MoveRejectReason.OCCUPIED


def test_occupied_center_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_move(moves=[(7, 7)], point=(7, 7))
    assert e.value.reason is MoveRejectReason.OCCUPIED


def test_move_outside_opening_zone_no_longer_rejected():
    # Дебютную зону validate_move больше НЕ сторожит (её закрывает фронт; на бэке зона —
    # поставщик ограничений, не сторож). Ход вне 3×3/5×5 проходит целостность.
    validate_move(moves=[(7, 7)], point=(5, 7))  # ход 2 вне 3×3 — не бросает
    validate_move(moves=[(7, 7), (8, 8)], point=(10, 7))  # ход 3 вне 5×5 — не бросает


def test_foul_point_no_longer_rejected():
    # Фолы validate_move больше НЕ сторожит (движок соблюдает сам, человеку перекрыты
    # фронтом). Ход в бывшую forbidden-точку проходит целостность.
    validate_move(moves=[(7, 7), (8, 8)], point=(9, 9))  # не бросает


# rj-8sc — статус-машина этапа 2: проверка очереди снята с доменного правила
# (validate_move не знает про статус/роль). Вернуть вместе со статус-машиной.
# def test_not_your_turn_rejected_by_color(): ...
# def test_opponent_thinking_rejected(): ...


def test_undo_black_human_at_preset_floor_rejected():
    # preset-модель: [center, white] — ход чёрного, но чёрный ещё не делал
    # реального хода (центр — старт). Откат недопустим.
    with pytest.raises(UndoRejected) as e:
        undo_truncate(moves=[(7, 7), (8, 8)], for_color=Color.BLACK)
    assert e.value.reason is UndoRejectReason.NOTHING_TO_UNDO


def test_undo_black_human_after_own_finishing_move_removes_one():
    # партия закончилась ходом чёрного человека (нечётная длина) → убрать один
    moves = [(7, 7), (8, 8), (7, 8)]
    assert undo_truncate(moves=moves, for_color=Color.BLACK) == [(7, 7), (8, 8)]


def test_undo_white_human_removes_engine_and_own_move():
    # белый человек: [B, W, B] → очередь белых после усечения до 1 камня
    moves = [(7, 7), (8, 8), (9, 9)]
    assert undo_truncate(moves=moves, for_color=Color.WHITE) == [(7, 7)]


def test_undo_white_human_after_own_finishing_move_removes_one():
    moves = [(7, 7), (8, 8), (9, 9), (8, 9)]
    assert undo_truncate(moves=moves, for_color=Color.WHITE) == [(7, 7), (8, 8), (9, 9)]


def test_undo_black_human_with_empty_board_rejected():
    with pytest.raises(UndoRejected) as e:
        undo_truncate(moves=[], for_color=Color.BLACK)
    assert e.value.reason is UndoRejectReason.NOTHING_TO_UNDO


def test_undo_white_human_with_only_engine_move_rejected():
    # у белого человека ещё нет своих ходов — откатывать нечего
    with pytest.raises(UndoRejected) as e:
        undo_truncate(moves=[(7, 7)], for_color=Color.WHITE)
    assert e.value.reason is UndoRejectReason.NOTHING_TO_UNDO
