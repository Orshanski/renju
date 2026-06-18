"""Протокол Piskvork/yx Rapfi: сборка команд и парсинг строк. Чистые функции.

Форматы сняты с реального бинаря (Rapfi 0.43.02):
- ход: голая строка "x,y" (например "5,4");
- фолы: "FORBID 0707." — пары %02d%02d (x, потом y), завершаются точкой; пусто: "FORBID .";
- ошибки: "ERROR <текст>"; подтверждение START: "OK";
- шум: "MESSAGE …", "DEBUG …", "INFO …" и прочее не подходящее под форматы выше.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..domain.engine_params import EngineParams
from ..domain.values import BOARD_SIZE, Point

_MOVE_RE = re.compile(r"^(\d{1,2}),(\d{1,2})$")
_FORBID_RE = re.compile(r"^FORBID ?((?:\d{4})*)\.$")


class ProtocolError(Exception):
    """Ответ движка не соответствует протоколу."""


class LineKind(StrEnum):
    OK = "ok"
    MOVE = "move"
    FORBID = "forbid"
    ERROR = "error"
    NOISE = "noise"


@dataclass(frozen=True)
class ParsedLine:
    kind: LineKind
    text: str
    move: Point | None = None
    forbidden: tuple[Point, ...] | None = None


def parse_line(raw: str) -> ParsedLine:
    line = raw.strip()
    if line == "OK":
        return ParsedLine(LineKind.OK, line)
    if line.startswith("ERROR"):
        return ParsedLine(LineKind.ERROR, line)
    if m := _MOVE_RE.match(line):
        move = (int(m.group(1)), int(m.group(2)))
        if not _on_board(move):
            raise ProtocolError(f"move out of board: {line!r}")
        return ParsedLine(LineKind.MOVE, line, move=move)
    if line.startswith("FORBID"):
        m = _FORBID_RE.match(line)
        if not m:
            raise ProtocolError(f"malformed FORBID line: {line!r}")
        digits = m.group(1)
        points = tuple(
            (int(digits[i : i + 2]), int(digits[i + 2 : i + 4])) for i in range(0, len(digits), 4)
        )
        if not all(_on_board(p) for p in points):
            raise ProtocolError(f"forbid point out of board: {line!r}")
        return ParsedLine(LineKind.FORBID, line, forbidden=points)
    return ParsedLine(LineKind.NOISE, line)


def _on_board(point: Point) -> bool:
    return 0 <= point[0] < BOARD_SIZE and 0 <= point[1] < BOARD_SIZE


@dataclass(frozen=True)
class SyncPlan:
    """Как привести движок от synced к target ДЛЯ ЗАПРОСА ХОДА (compute_move).

    cold=True → послать START+INFO+BOARD(target), сбросив состояние; иначе —
    takebacks (координаты снимаемых камней, в порядке отправки) + один TURN."""

    cold: bool
    takebacks: tuple[Point, ...]
    turn: Point | None


def plan_sync(synced: Sequence[Point] | None, target: Sequence[Point]) -> SyncPlan:
    """Планировщик инкрементальной синхронизации позиции.

    Если synced is None — движок не инициализирован, нужен холодный старт.
    Иначе: находим общий префикс. tail=1 — TAKEBACK* + TURN; tail=0 —
    TAKEBACK* + YXNBEST 1 (думать на текущей доске). tail>1 — аномалия."""
    if synced is None:
        return SyncPlan(cold=True, takebacks=(), turn=None)
    n = 0
    while n < len(synced) and n < len(target) and synced[n] == target[n]:
        n += 1
    tail = target[n:]
    if len(tail) > 1:
        return SyncPlan(cold=True, takebacks=(), turn=None)
    takebacks = tuple(reversed(synced[n:]))
    return SyncPlan(cold=False, takebacks=takebacks, turn=tail[0] if tail else None)


def tunable_commands(params: EngineParams) -> list[str]:
    """Per-move INFO (сила/время/глубина). Шлём перед каждым расчётом.

    max_depth — обычный int 1..99, в stdin движка только проверенный int (анти-инъекция)."""
    return [
        f"INFO strength {params.strength}",
        f"INFO timeout_turn {params.timeout_turn_ms}",
        f"INFO max_depth {params.max_depth}",
    ]


def turn_commands(point: Point) -> list[str]:
    """TURN x,y — запрос хода от движка при инкрементальном режиме."""
    _validate_moves([point])
    x, y = point
    return [f"TURN {x},{y}"]


def think_commands() -> list[str]:
    """YXNBEST 1 — запросить лучший ход для текущей доски без добавления хода соперника."""
    return ["YXNBEST 1"]


def hashclear_commands() -> list[str]:
    """YXHASHCLEAR — очистить транспозиционную таблицу/search-state движка
    (gomocup.cpp:clearHash → Search::Threads.clear). Слать ПОСЛЕ TAKEBACK и ДО
    следующего расчёта: откат оставляет старый hash/cache, и движок на той же
    позиции отвечает иначе, чем на свежей. Ответ движка — MESSAGE (шум), не OK."""
    return ["YXHASHCLEAR"]


def takeback_commands(points: Sequence[Point]) -> list[str]:
    """TAKEBACK x,y на каждый снимаемый камень (gomocup.cpp:586 читает x,y и
    откатывает последний ход). Анти-инъекция: только int 0..14."""
    _validate_moves(points)
    return [f"TAKEBACK {x},{y}" for x, y in points]


def start_commands() -> list[str]:
    """START + правило: создаёт доску движка и ставит рэндзю. Инварианты процесса —
    шлются один раз на холодной синхронизации (свежий/респаун-процесс)."""
    return [f"START {BOARD_SIZE}", "INFO rule 4"]


def init_commands(params: EngineParams) -> list[str]:
    """Холодная инициализация хода: START + правило + per-move tunable."""
    return [*start_commands(), *tunable_commands(params)]


def position_commands(moves: Sequence[Point]) -> list[str]:
    """BOARD-блок для запроса хода (пустая позиция — BEGIN).

    who относительно стороны-на-ходу: 1 — её камни, 2 — соперника.
    Камни в порядке ходов (первый — чёрный)."""
    _validate_moves(moves)
    if not moves:
        return ["BEGIN"]
    return ["BOARD", *_stone_lines(moves), "DONE"]


def forbid_commands(moves: Sequence[Point]) -> list[str]:
    """YXBOARD-блок (ставит доску без расчёта) + запрос запрещённых точек."""
    _validate_moves(moves)
    return ["YXBOARD", *_stone_lines(moves), "DONE", "YXSHOWFORBID"]


def block_commands(block_points: Sequence[Point]) -> list[str]:
    """YXBLOCK-блок: ['YXBLOCK', 'x,y', ..., 'DONE'] для непустого списка, иначе [].

    Формат снят с движка (gomocup.cpp:getBlock): 'x,y' до DONE, без поля who.
    Анти-инъекция (§5.2): в stdin — только int 0..14."""
    if not block_points:
        return []
    _validate_moves(block_points)
    return ["YXBLOCK", *[f"{x},{y}" for x, y in block_points], "DONE"]


def _stone_lines(moves: Sequence[Point]) -> list[str]:
    side_to_move_parity = len(moves) % 2
    return [f"{x},{y},{1 if i % 2 == side_to_move_parity else 2}" for i, (x, y) in enumerate(moves)]


def _validate_moves(moves: Sequence[Point]) -> None:
    """Анти-инъекция (спек §5.2): в stdin движка уходят только int 0..14.

    bool — подкласс int, отвергаем явно. Дубликаты — битая позиция."""
    seen: set[Point] = set()
    for point in moves:
        if not (isinstance(point, tuple) and len(point) == 2):
            raise ProtocolError(f"malformed point: {point!r}")
        x, y = point
        if isinstance(x, bool) or isinstance(y, bool):
            raise ProtocolError(f"non-int coordinates: {point!r}")
        if not (isinstance(x, int) and isinstance(y, int)):
            raise ProtocolError(f"non-int coordinates: {point!r}")
        if not _on_board((x, y)):
            raise ProtocolError(f"point out of board: {point!r}")
        if (x, y) in seen:
            raise ProtocolError(f"duplicate point: {point!r}")
        seen.add((x, y))
