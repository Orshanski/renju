import pytest

from app.domain.engine_params import EngineParams
from app.domain.opening import opening_zone
from app.domain.values import MoveRejected, MoveRejectReason
from app.game.moves import apply_move, engine_move, new_game


def test_new_game_starts_with_center():
    assert new_game() == [(7, 7)]


def test_apply_move_valid_appends():
    assert apply_move([(7, 7)], (8, 8)) == [(7, 7), (8, 8)]


def test_apply_move_occupied_rejected():
    with pytest.raises(MoveRejected) as e:
        apply_move([(7, 7), (8, 8)], (8, 8))
    assert e.value.reason is MoveRejectReason.OCCUPIED


def test_apply_move_outside_opening_zone_no_longer_rejected():
    # дебютную зону apply_move больше не сторожит (фронт её закрывает) — ход вне 3×3 проходит
    assert apply_move([(7, 7)], (5, 7)) == [(7, 7), (5, 7)]


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
        apply_move(moves, (8, 8))
    assert e.value.reason is MoveRejectReason.GAME_FINISHED


class _FakeAdapter:
    def __init__(self):
        self.received_zone = "unset"
        self.received_game_id = None

    async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
        self.received_zone = allowed_zone
        self.received_game_id = game_id
        return (8, 8)


async def test_engine_move_passes_opening_zone_as_allowed_zone():
    fake = _FakeAdapter()
    params = EngineParams(strength=50, timeout_turn_ms=1000)
    move = await engine_move(fake, [(7, 7)], params, "g1")  # type: ignore[arg-type]
    assert move == (8, 8)
    assert fake.received_zone == opening_zone(1) and fake.received_game_id == "g1"


async def test_engine_move_unrestricted_after_opening():
    fake = _FakeAdapter()
    params = EngineParams(strength=50, timeout_turn_ms=1000)
    await engine_move(fake, [(7, 7), (8, 8), (9, 9), (6, 6)], params, "g2")  # type: ignore[arg-type]
    assert fake.received_zone is None


async def test_engine_move_no_block_on_black_third_move():
    # Чёрный 3-й ход (len==2, зона 5×5): YXBLOCK искажает поиск движка → слив (raw-прогоны
    # живого движка, 100/100). Зону НЕ накладываем — движок сам в 5×5 ~99%, обуздание лишь ломает.
    fake = _FakeAdapter()
    params = EngineParams(strength=50, timeout_turn_ms=1000)
    await engine_move(fake, [(7, 7), (8, 8)], params, "g3")  # type: ignore[arg-type]
    assert fake.received_zone is None
