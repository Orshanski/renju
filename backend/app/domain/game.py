"""Игровая логика партии: валидация хода, усечение undo. Чистые функции."""

from collections.abc import Sequence

from app.domain.opening import opening_zone
from app.domain.values import (
    BOARD_SIZE,
    Color,
    MoveRejected,
    MoveRejectReason,
    Point,
    UndoRejected,
    UndoRejectReason,
    color_to_move,
)


def validate_move(
    *,
    moves: Sequence[Point],
    point: Point,
    forbidden: Sequence[Point],
) -> None:
    """Бросает MoveRejected, если ход недопустим ПО ПРАВИЛАМ (геометрия → занятость →
    дебютная зона → фол). Статус партии и очередь — оркестрация, не здесь.
    Сторона-на-ходу выводится из len(moves); роль (человек/ИИ) не нужна."""
    x, y = point
    if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
        raise MoveRejected(MoveRejectReason.OUT_OF_BOARD)
    if point in set(moves):
        raise MoveRejected(MoveRejectReason.OCCUPIED)
    zone = opening_zone(len(moves))
    if zone is not None and point not in zone:
        raise MoveRejected(MoveRejectReason.OPENING_VIOLATION)
    if color_to_move(len(moves)) is Color.BLACK and point in set(forbidden):
        raise MoveRejected(MoveRejectReason.FORBIDDEN)


def undo_truncate(*, moves: Sequence[Point], for_color: Color, preset: int = 1) -> list[Point]:
    """Усечь ходы до предыдущего состояния «ход for_color», не снимая preset
    стартовых камней (центр предзаполнен). Новая длина k — наибольшая
    preset ≤ k < len(moves) c очередью for_color (k чётно для чёрных, нечётно для белых).
    Если такого k нет — NOTHING_TO_UNDO. (for_color — сторона, для которой откат;
    источник хода — человек/ИИ — не важен.)"""
    target_parity = 0 if for_color is Color.BLACK else 1
    k = len(moves) - 1
    while k >= preset and k % 2 != target_parity:
        k -= 1
    if k < preset:
        raise UndoRejected(UndoRejectReason.NOTHING_TO_UNDO)
    return list(moves[:k])
