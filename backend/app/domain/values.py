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
    AWAITING_MOVE = "awaiting_move"
    OPPONENT_THINKING = "opponent_thinking"
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
