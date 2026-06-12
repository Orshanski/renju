"""Undo-политика пользователя (глобальная настройка, спек §4.3/§4.8)."""

from dataclasses import dataclass

from app.domain.values import GameStatus, UndoRejected, UndoRejectReason


@dataclass(frozen=True)
class UndoPolicy:
    enabled: bool = True
    limit: int | None = None  # None — без лимита
    after_game_end: bool = True


def check_undo(*, policy: UndoPolicy, status: GameStatus, undo_count: int) -> None:
    """Бросает UndoRejected, если откат запрещён политикой или состоянием партии."""
    if not policy.enabled:
        raise UndoRejected(UndoRejectReason.DISABLED)
    if status is GameStatus.OPPONENT_THINKING:
        raise UndoRejected(UndoRejectReason.OPPONENT_THINKING)
    if status.is_finished and not policy.after_game_end:
        raise UndoRejected(UndoRejectReason.GAME_FINISHED)
    if policy.limit is not None and undo_count >= policy.limit:
        raise UndoRejected(UndoRejectReason.LIMIT_REACHED)
