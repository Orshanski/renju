"""Игровая логика партии: валидация хода человека, усечение undo. Чистые функции."""

from collections.abc import Sequence

from app.domain.values import (
    BOARD_SIZE,
    Color,
    GameStatus,
    MoveRejected,
    MoveRejectReason,
    Point,
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
