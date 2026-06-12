"""Фасад хода/партии: оркестрация поверх домена и адаптера Rapfi (§4.9).

Прячет дебютную механику (allowed_zone) и проверку завершённости. Этап 1 — тонкий
модуль; на этапе 2 дозреет до game-service с БД/статусами (тикет rj-8sc — очередь)."""

from collections.abc import Sequence

from .domain.engine_params import EngineParams
from .domain.game import validate_move
from .domain.opening import CENTER, opening_zone
from .domain.rules import outcome_after
from .domain.values import MoveRejected, MoveRejectReason, Point
from .rapfi.adapter import RapfiAdapter


def new_game() -> list[Point]:
    """Стартовая позиция: чёрный камень в центре (RIF ход 1 предопределён, не выбор)."""
    return [CENTER]


def apply_move(moves: Sequence[Point], point: Point, *, forbidden: Sequence[Point]) -> list[Point]:
    """Применить предложенный ход: завершённость (оркестрация) + правило хода.
    Источник хода (человек/движок) не важен."""
    if outcome_after(moves) is not None:
        raise MoveRejected(MoveRejectReason.GAME_FINISHED)
    validate_move(moves=moves, point=point, forbidden=forbidden)
    return [*moves, point]


async def engine_move(adapter: RapfiAdapter, moves: Sequence[Point], params: EngineParams) -> Point:
    """Ход движка для позиции; дебютное обуздание спрятано. Инвариант: moves
    непуст (центр предзаполнен new_game), поэтому allowed_zone не бывает синглтоном."""
    zone = opening_zone(len(moves))
    return await adapter.compute_move(moves, params, allowed_zone=zone)
