"""Доменные ошибки рэндзю. Без I/O."""

from enum import StrEnum


class DomainError(Exception):
    """База для доменных ошибок."""


class MoveRejectReason(StrEnum):
    OUT_OF_BOARD = "out_of_board"
    OCCUPIED = "occupied"
    NOT_YOUR_TURN = "not_your_turn"
    FORBIDDEN = "forbidden"
    OPENING_VIOLATION = "opening_violation"
    GAME_FINISHED = "game_finished"
    OPPONENT_THINKING = "opponent_thinking"


class MoveRejected(DomainError):
    def __init__(self, reason: MoveRejectReason):
        self.reason = reason
        super().__init__(reason.value)


class UndoRejectReason(StrEnum):
    DISABLED = "disabled"
    OPPONENT_THINKING = "opponent_thinking"
    GAME_FINISHED = "game_finished"
    LIMIT_REACHED = "limit_reached"
    NOTHING_TO_UNDO = "nothing_to_undo"


class UndoRejected(DomainError):
    def __init__(self, reason: UndoRejectReason):
        self.reason = reason
        super().__init__(reason.value)
