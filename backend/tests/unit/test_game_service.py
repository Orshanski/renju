import pytest

from app.domain.engine_params import EngineParams
from app.domain.opening import opening_zone
from app.domain.values import MoveRejected, MoveRejectReason
from app.game_service import apply_move, engine_move, new_game


def test_new_game_starts_with_center():
    assert new_game() == [(7, 7)]


def test_apply_move_valid_appends():
    assert apply_move([(7, 7)], (8, 8), forbidden=[]) == [(7, 7), (8, 8)]


def test_apply_move_occupied_rejected():
    with pytest.raises(MoveRejected) as e:
        apply_move([(7, 7), (8, 8)], (8, 8), forbidden=[])
    assert e.value.reason is MoveRejectReason.OCCUPIED


def test_apply_move_opening_violation_rejected():
    with pytest.raises(MoveRejected) as e:
        apply_move([(7, 7)], (5, 7), forbidden=[])  # ход 2 вне 3×3
    assert e.value.reason is MoveRejectReason.OPENING_VIOLATION


def test_apply_move_on_finished_game_rejected():
    # реально выигранная позиция: пять чёрных в ряд по горизонтали.
    # чёрные — чётные индексы; строим перемежая ходами белых так, чтобы
    # последний (выигрышный) ход сделали чёрные.
    moves = [
        (3, 7),
        (3, 0),  # B,(W)
        (4, 7),
        (4, 0),
        (5, 7),
        (5, 0),
        (6, 7),
        (6, 0),
        (7, 7),  # пятый чёрный в ряд (3..7, y=7) → finished_black
    ]
    from app.domain.rules import outcome_after
    from app.domain.values import GameStatus

    assert outcome_after(moves) is GameStatus.FINISHED_BLACK  # предпосылка теста
    with pytest.raises(MoveRejected) as e:
        apply_move(moves, (8, 8), forbidden=[])
    assert e.value.reason is MoveRejectReason.GAME_FINISHED


class _FakeAdapter:
    def __init__(self):
        self.received_zone = "unset"

    async def compute_move(self, moves, params, allowed_zone=None):
        self.received_zone = allowed_zone
        return (8, 8)


async def test_engine_move_passes_opening_zone_as_allowed_zone():
    fake = _FakeAdapter()
    moves = [(7, 7)]  # ход 2 → зона 3×3
    params = EngineParams(strength=50, timeout_turn_ms=1000)
    move = await engine_move(fake, moves, params)  # type: ignore[arg-type]  # _FakeAdapter — дубль
    assert move == (8, 8)
    assert fake.received_zone == opening_zone(1)


async def test_engine_move_unrestricted_after_opening():
    fake = _FakeAdapter()
    moves = [(7, 7), (8, 8), (9, 9), (6, 6)]  # len=4 → зона None
    params = EngineParams(strength=50, timeout_turn_ms=1000)
    await engine_move(fake, moves, params)  # type: ignore[arg-type]
    assert fake.received_zone is None
