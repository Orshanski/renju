"""Фасад хода/партии: оркестрация поверх домена и адаптера Rapfi (§4.9).

Прячет дебютную механику (allowed_zone) и проверку завершённости. Этап 1 — тонкий
модуль; на этапе 2 дозреет до game-service с БД/статусами (тикет rj-8sc — очередь)."""

from collections.abc import Sequence

from .domain.engine_params import EngineParams
from .domain.game import validate_move
from .domain.opening import CENTER, opening_zone
from .domain.rules import outcome_after
from .domain.values import MoveRejected, MoveRejectReason, Point


def new_game() -> list[Point]:
    """Стартовая позиция: чёрный камень в центре (RIF ход 1 предопределён, не выбор)."""
    return [CENTER]


def apply_move(moves: Sequence[Point], point: Point) -> list[Point]:
    """Применить предложенный ход: завершённость (оркестрация) + целостность хода
    (геометрия/занятость). Дебютную зону и фолы не сторожит (см. validate_move).
    Источник хода (человек/движок) не важен."""
    if outcome_after(moves) is not None:
        raise MoveRejected(MoveRejectReason.GAME_FINISHED)
    validate_move(moves=moves, point=point)
    return [*moves, point]


async def engine_move(
    adapter, moves: Sequence[Point], params: EngineParams, game_id: str, level_tag: str = "-"
) -> Point:
    """Ход движка для позиции; дебютное обуздание спрятано. Инвариант: moves
    непуст (центр предзаполнен new_game), поэтому allowed_zone не бывает синглтоном.
    game_id — ПЕРВЫЙ позиционный у adapter (см. EngineRegistry.compute_move).

    YXBLOCK-обуздание ≠ правило валидации (domain.validate_move оставляет 5×5 на 3-м
    ходу как ПРАВИЛО). Здесь — только ограничение поиска движка, и его накладываем
    ТОЛЬКО на белый 2-й ход (len==1, зона 3×3): сам движок попадает в 3×3 лишь ~40%,
    а YXBLOCK там безопасен. На чёрном 3-м ходу (len==2, 5×5) YXBLOCK искажает поиск
    движка → слив (проверено raw-прогонами живого движка, 100/100); в 5×5 он и так сам
    кладёт ~99%, поэтому зону НЕ накладываем (на редкий выход не рубим — допускаем ~1/100)."""
    zone = opening_zone(len(moves)) if len(moves) == 1 else None
    return await adapter.compute_move(
        game_id, moves, params, allowed_zone=zone, level_tag=level_tag
    )
