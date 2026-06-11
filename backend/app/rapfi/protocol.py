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

from app.domain.levels import EngineParams
from app.domain.values import BOARD_SIZE, Point

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


def init_commands(params: EngineParams) -> list[str]:
    """Переинициализация перед каждым расчётом — состояние партий не протекает."""
    return [
        f"START {BOARD_SIZE}",
        "INFO rule 4",
        f"INFO strength {params.strength}",
        f"INFO timeout_turn {params.timeout_turn_ms}",
    ]


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
