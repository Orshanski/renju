"""Игровая логика партии: валидация хода человека, усечение undo. Чистые функции."""

from collections.abc import Sequence

from app.domain.values import (
    BOARD_SIZE,
    Color,
    GameStatus,
    MoveRejected,
    MoveRejectReason,
    Point,
    UndoRejected,
    UndoRejectReason,
    color_to_move,
)


def validate_human_move(
    *,
    moves: Sequence[Point],
    human_color: Color,
    status: GameStatus,
    point: Point,
    forbidden: Sequence[Point],
) -> None:
    """Бросает MoveRejected, если ход человека недопустим. Порядок проверок важен:
    сначала состояние партии, потом геометрия, потом фолы."""
    if status.is_finished:
        raise MoveRejected(MoveRejectReason.GAME_FINISHED)
    if status is not GameStatus.AWAITING_HUMAN:
        raise MoveRejected(MoveRejectReason.NOT_YOUR_TURN)
    if color_to_move(len(moves)) is not human_color:
        raise MoveRejected(MoveRejectReason.NOT_YOUR_TURN)
    x, y = point
    if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
        raise MoveRejected(MoveRejectReason.OUT_OF_BOARD)
    if point in set(moves):
        raise MoveRejected(MoveRejectReason.OCCUPIED)
    if human_color is Color.BLACK and point in set(forbidden):
        raise MoveRejected(MoveRejectReason.FORBIDDEN)


def undo_truncate(*, moves: Sequence[Point], human_color: Color) -> list[Point]:
    """Усечь ходы до предыдущего состояния «ход человека».

    Новая длина k — наибольшая k < len(moves), при которой очередь человека:
    k чётно для чёрных, нечётно для белых. Обычно убирает 2 камня (ход ИИ + свой),
    после завершающего хода человека — 1.
    """
    target_parity = 0 if human_color is Color.BLACK else 1
    k = len(moves) - 1
    while k >= 0 and k % 2 != target_parity:
        k -= 1
    if k < 0:
        raise UndoRejected(UndoRejectReason.NOTHING_TO_UNDO)
    return list(moves[:k])
