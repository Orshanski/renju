"""Протокол Piskvork/yx Rapfi: сборка команд и парсинг строк. Чистые функции.

Форматы сняты с реального бинаря (Rapfi 0.43.02):
- ход: голая строка "x,y" (например "5,4");
- фолы: "FORBID 0707." — пары %02d%02d (x, потом y), завершаются точкой; пусто: "FORBID .";
- ошибки: "ERROR <текст>"; подтверждение START: "OK";
- шум: "MESSAGE …", "DEBUG …", "INFO …" и прочее не подходящее под форматы выше.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

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
            (int(digits[i : i + 2]), int(digits[i + 2 : i + 4]))
            for i in range(0, len(digits), 4)
        )
        if not all(_on_board(p) for p in points):
            raise ProtocolError(f"forbid point out of board: {line!r}")
        return ParsedLine(LineKind.FORBID, line, forbidden=points)
    return ParsedLine(LineKind.NOISE, line)


def _on_board(point: Point) -> bool:
    return 0 <= point[0] < BOARD_SIZE and 0 <= point[1] < BOARD_SIZE
