"""Базовые типы домена рэндзю. Без I/O."""

from enum import StrEnum

BOARD_SIZE = 15
MAX_MOVES = BOARD_SIZE * BOARD_SIZE

# Точка доски: (x, y), оба в 0..14. Ходы партии — список точек в порядке ходов;
# цвет хода определяется чётностью индекса (первый ход — чёрные).
Point = tuple[int, int]


class Color(StrEnum):
    BLACK = "black"
    WHITE = "white"


class GameStatus(StrEnum):
    AWAITING_HUMAN = "awaiting_human"
    ENGINE_THINKING = "engine_thinking"
    FINISHED_BLACK = "finished_black"
    FINISHED_WHITE = "finished_white"
    FINISHED_DRAW = "finished_draw"

    @property
    def is_finished(self) -> bool:
        return self in (
            GameStatus.FINISHED_BLACK,
            GameStatus.FINISHED_WHITE,
            GameStatus.FINISHED_DRAW,
        )


def color_of_move(index: int) -> Color:
    return Color.BLACK if index % 2 == 0 else Color.WHITE


def color_to_move(moves_count: int) -> Color:
    return color_of_move(moves_count)


class DomainError(Exception):
    """База для доменных ошибок."""


class MoveRejectReason(StrEnum):
    OUT_OF_BOARD = "out_of_board"
    OCCUPIED = "occupied"
    NOT_YOUR_TURN = "not_your_turn"
    FORBIDDEN = "forbidden"
    GAME_FINISHED = "game_finished"


class MoveRejected(DomainError):
    def __init__(self, reason: MoveRejectReason):
        self.reason = reason
        super().__init__(reason.value)


class UndoRejectReason(StrEnum):
    DISABLED = "disabled"
    ENGINE_THINKING = "engine_thinking"
    GAME_FINISHED = "game_finished"
    LIMIT_REACHED = "limit_reached"
    NOTHING_TO_UNDO = "nothing_to_undo"


class UndoRejected(DomainError):
    def __init__(self, reason: UndoRejectReason):
        self.reason = reason
        super().__init__(reason.value)
