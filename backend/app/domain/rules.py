"""Исходы партии. Детекция по последнему ходу; чистые функции."""

from collections.abc import Sequence

from .values import MAX_MOVES, Color, GameStatus, Point, color_of_move

_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


def outcome_after(moves: Sequence[Point]) -> GameStatus | None:
    """Статус-исход после последнего хода или None, если партия продолжается.

    Рэндзю: чёрные выигрывают ровно пятёркой (оверлайн — не победа),
    белые — пятёркой и длиннее. Ничья — полная доска (225) без победы.

    Проверяется только линия последнего хода; набор своих камней (own)
    пересобирается за O(n) на каждый вызов — инкрементного состояния нет.
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


def winning_line(moves: Sequence[Point]) -> list[Point] | None:
    """Точки выигрышной серии последнего хода (вдоль направления, по порядку), или None.

    Те же правила, что outcome_after: чёрные — ровно 5, белые — 5 и длиннее
    (оверлайн возвращается целиком). Партия идёт / ничья → None.
    Один ход замкнул две линии → первая по порядку _DIRECTIONS (для подсветки
    достаточно одной, выбор детерминирован).
    """
    if not moves:
        return None
    last = moves[-1]
    mover = color_of_move(len(moves) - 1)
    own = {moves[i] for i in range(len(moves)) if color_of_move(i) is mover}
    for dx, dy in _DIRECTIONS:
        back = _ray_points(own, last, -dx, -dy)
        fwd = _ray_points(own, last, dx, dy)
        run = 1 + len(back) + len(fwd)
        if (mover is Color.BLACK and run == 5) or (mover is Color.WHITE and run >= 5):
            return list(reversed(back)) + [last] + fwd
    return None


def _ray_points(own: set[Point], start: Point, dx: int, dy: int) -> list[Point]:
    """Свои камни подряд от start в направлении (dx, dy), не считая start."""
    pts: list[Point] = []
    x, y = start[0] + dx, start[1] + dy
    while (x, y) in own:
        pts.append((x, y))
        x, y = x + dx, y + dy
    return pts


def _ray(own: set[Point], start: Point, dx: int, dy: int) -> int:
    """Сколько своих камней подряд от start в направлении (dx, dy), не считая start."""
    return len(_ray_points(own, start, dx, dy))
