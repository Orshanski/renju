"""Исходы партии. Детекция по последнему ходу; чистые функции."""

from collections.abc import Sequence

from app.domain.values import MAX_MOVES, Color, GameStatus, Point, color_of_move

_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


def outcome_after(moves: Sequence[Point]) -> GameStatus | None:
    """Статус-исход после последнего хода или None, если партия продолжается.

    Рэндзю: чёрные выигрывают ровно пятёркой (оверлайн — не победа),
    белые — пятёркой и длиннее. Ничья — полная доска (225) без победы.
    """
    if not moves:
        return None
    last = moves[-1]
    mover = color_of_move(len(moves) - 1)
    own = {moves[i] for i in range(len(moves)) if color_of_move(i) is mover}
    for dx, dy in _DIRECTIONS:
        run = 1 + _ray(own, last, dx, dy) + _ray(own, last, -dx, -dy)
        if mover is Color.BLACK and run == 5:
            return GameStatus.FINISHED_BLACK
        if mover is Color.WHITE and run >= 5:
            return GameStatus.FINISHED_WHITE
    if len(moves) == MAX_MOVES:
        return GameStatus.FINISHED_DRAW
    return None


def _ray(own: set[Point], start: Point, dx: int, dy: int) -> int:
    """Сколько своих камней подряд от start в направлении (dx, dy), не считая start."""
    count = 0
    x, y = start[0] + dx, start[1] + dy
    while (x, y) in own:
        count += 1
        x, y = x + dx, y + dy
    return count
