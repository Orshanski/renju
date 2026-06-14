"""Хелперы протокола Rapfi: команды движка и обработка ошибок.

Используются EngineRegistry (registry.py).
"""

from collections.abc import Sequence

from ..domain.engine_params import EngineParams
from ..domain.values import BOARD_SIZE, Point
from .protocol import (
    SyncPlan,
    block_commands,
    hashclear_commands,
    init_commands,
    position_commands,
    takeback_commands,
    think_commands,
    tunable_commands,
    turn_commands,
)

# Сколько добавить к timeout_turn движка до wall-clock kill: движок укладывается
# в свой бюджет сам, запас покрывает инициализацию (загрузку весов) и парсинг.
_WALL_CLOCK_SLACK_S = 5.0
_FORBID_TIMEOUT_S = 10.0


class EngineError(Exception):
    """Движок не смог посчитать (после повтора). Несёт текст причины."""


def _zone_block(moves: Sequence[Point], allowed_zone: frozenset[Point] | None) -> list[str]:
    """YXBLOCK-блок: все свободные клетки вне зоны. [] если зоны нет."""
    if allowed_zone is None:
        return []
    if not allowed_zone:
        raise ValueError("allowed_zone must be None or non-empty")
    occupied = set(moves)
    block = [
        (x, y)
        for x in range(BOARD_SIZE)
        for y in range(BOARD_SIZE)
        if (x, y) not in allowed_zone and (x, y) not in occupied
    ]
    return block_commands(block)


def _move_commands(
    moves: Sequence[Point],
    params: EngineParams,
    allowed_zone: frozenset[Point] | None,
) -> list[str]:
    """COLD: init(START+INFO) + [YXBLOCK] + BOARD(moves) + [YXBLOCKRESET].

    Блок — свободные клетки вне зоны (all − занятые − зона). Парность гарантирует:
    блок живёт только внутри этого запроса, в памяти движка между запросами ничего
    не остаётся (START blockMoves не чистит — поэтому снимаем явно)."""
    commands = init_commands(params)
    block = _zone_block(moves, allowed_zone)
    commands += block + position_commands(moves)
    if block:
        commands += ["YXBLOCKRESET"]
    return commands


def incremental_move_commands(
    plan: SyncPlan,
    *,
    target: Sequence[Point],
    params: EngineParams,
    allowed_zone: frozenset[Point] | None,
) -> list[str]:
    """Тёплый ход: TAKEBACK(хвост) → [YXHASHCLEAR] → per-move INFO → [YXBLOCK]→TURN/YXNBEST→[RESET].

    `TURN` используется, когда есть новый ход человека; `YXNBEST 1` — когда после
    TAKEBACK нужно думать на уже текущей доске.

    YXHASHCLEAR — ТОЛЬКО когда был откат (plan.takebacks непуст): снятый суффикс
    оставляет в транспозиционной таблице (TT) записи от уже несуществующих линий, и
    движок на возвращённой позиции отвечает не как на свежей (проверено прогоном
    живого движка: TAKEBACK→TURN даёт стухший ход, TAKEBACK→YXHASHCLEAR→TURN — тот
    же ход, что START+BOARD на этой позиции). На обычном ходе вперёд (без отката)
    тёплая TT полезна — её НЕ чистим. clearHash чистит только TT, не историю, но
    эмпирически для нашего бюджета этого достаточно."""
    assert not plan.cold
    block = _zone_block(target, allowed_zone)
    cmds = [
        *takeback_commands(plan.takebacks),
        *(hashclear_commands() if plan.takebacks else []),
        *tunable_commands(params),
        *block,
        *(turn_commands(plan.turn) if plan.turn is not None else think_commands()),
    ]
    if block:
        cmds.append("YXBLOCKRESET")
    return cmds
