"""Дебютная зона рэндзю (RIF Уровень 1). Чистая геометрия, без I/O, без ролей."""

from .values import Point

CENTER: Point = (7, 7)


def opening_zone(move_count: int) -> frozenset[Point] | None:
    """Разрешённые клетки для хода № move_count (= len(moves)).

    0 → {центр} (в партии не встречается — центр предзаполнен, см. game.moves.new_game),
    1 → центральный 3×3, 2 → центральный 5×5, ≥3 → None (без ограничений).
    Чистая геометрия квадрата; занятость не вычитается (проверяется отдельно)."""
    if move_count == 0:
        return frozenset({CENTER})
    if move_count == 1:
        return _square(1)
    if move_count == 2:
        return _square(2)
    return None


def _square(radius: int) -> frozenset[Point]:
    cx, cy = CENTER
    return frozenset(
        (x, y)
        for x in range(cx - radius, cx + radius + 1)
        for y in range(cy - radius, cy + radius + 1)
    )
