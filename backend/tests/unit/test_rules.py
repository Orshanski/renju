from app.domain.rules import outcome_after, winning_line
from app.domain.values import BOARD_SIZE, MAX_MOVES, GameStatus, Point


def interleave(blacks: list[Point], whites: list[Point]) -> list[Point]:
    """Сплести списки в порядок ходов: B, W, B, W, …"""
    moves: list[Point] = []
    for i in range(len(blacks) + len(whites)):
        moves.append(blacks[i // 2] if i % 2 == 0 else whites[i // 2])
    return moves


def test_empty_and_short_games_are_not_finished():
    assert outcome_after([]) is None
    assert outcome_after([(7, 7)]) is None


def test_black_five_horizontal_wins():
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]
    whites = [(0, 0), (2, 0), (4, 0), (6, 0)]  # вразброс — без побочных линий
    moves = interleave(blacks, whites)  # последний ход — чёрный (7,7)
    assert outcome_after(moves) is GameStatus.FINISHED_BLACK


def test_black_five_diagonal_wins():
    blacks = [(3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]
    whites = [(0, 5), (0, 7), (0, 9), (0, 11)]
    assert outcome_after(interleave(blacks, whites)) is GameStatus.FINISHED_BLACK


def test_black_four_is_not_a_win():
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7)]
    whites = [(0, 0), (2, 0), (4, 0)]
    assert outcome_after(interleave(blacks, whites)) is None


def test_black_overline_is_not_a_win():
    # 6 чёрных в ряд (на практике заблокировано фолами, но правило фиксируем)
    blacks = [(2, 7), (3, 7), (4, 7), (6, 7), (7, 7), (5, 7)]  # (5,7) замыкает шестёрку
    whites = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)]  # вразброс
    assert outcome_after(interleave(blacks, whites)) is None


def test_white_five_vertical_wins():
    blacks = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)]  # вразброс
    whites = [(7, 3), (7, 4), (7, 5), (7, 6), (7, 7)]
    moves = interleave(blacks, whites)  # последний ход — белый (7,7)
    assert outcome_after(moves) is GameStatus.FINISHED_WHITE


def test_white_overline_wins():
    blacks = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0)]  # вразброс
    whites = [(7, 2), (7, 3), (7, 4), (7, 6), (7, 7), (7, 5)]  # (7,5) замыкает шестёрку
    assert outcome_after(interleave(blacks, whites)) is GameStatus.FINISHED_WHITE


def test_win_detection_uses_only_last_move_color():
    # пятёрка белых уже стоит, но последний ход чёрный и ничего не выигрывает:
    # функция смотрит только на линию последнего хода (own пересобирается каждый раз)
    blacks = [(0, 0), (1, 1), (2, 2), (3, 3), (0, 4), (0, 6)]
    whites = [(7, 3), (7, 4), (7, 5), (7, 6), (7, 7)]
    moves = interleave(blacks, whites)  # 11 ходов, последний — чёрный (0,6)
    assert outcome_after(moves) is None


def test_full_board_without_five_is_draw():
    # Раскраска цвет(x,y) = (x + 2y) % 4 < 2: максимум 2 подряд в любом из
    # 4 направлений (горизонталь BBWW…, вертикаль BWBW…, диагонали BWWB…).
    # NB: раскраска 2×2-блоками (x//2+y//2)%2 НЕ подходит — на главной
    # диагонали (k,k) она даёт один цвет на все 15 клеток.
    blacks = [(x, y) for y in range(BOARD_SIZE) for x in range(BOARD_SIZE) if (x + 2 * y) % 4 < 2]
    whites = [(x, y) for y in range(BOARD_SIZE) for x in range(BOARD_SIZE) if (x + 2 * y) % 4 >= 2]
    assert len(blacks) == 113 and len(whites) == 112  # чёрные ходят первыми
    moves = interleave(blacks, whites)
    assert len(moves) == MAX_MOVES
    assert outcome_after(moves) is GameStatus.FINISHED_DRAW


def test_winning_line_black_horizontal():
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]
    whites = [(0, 0), (2, 0), (4, 0), (6, 0)]
    line = winning_line(interleave(blacks, whites))
    assert line == [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]  # вдоль направления, по возрастанию


def test_winning_line_black_diagonal():
    blacks = [(3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]
    whites = [(0, 5), (0, 7), (0, 9), (0, 11)]
    assert winning_line(interleave(blacks, whites)) == [(3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]


def test_winning_line_white_overline_last_move_mid_series():
    # последний белый ход (7,5) — В СЕРЕДИНЕ серии: лучи в обе стороны, вся шестёрка
    blacks = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0)]
    whites = [(7, 2), (7, 3), (7, 4), (7, 6), (7, 7), (7, 5)]
    line = winning_line(interleave(blacks, whites))
    assert line == [(7, 2), (7, 3), (7, 4), (7, 5), (7, 6), (7, 7)]  # оверлайн целиком


def test_winning_line_none_when_game_ongoing():
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7)]  # четвёрка — не победа
    whites = [(0, 0), (2, 0), (4, 0)]
    assert winning_line(interleave(blacks, whites)) is None


def test_winning_line_none_for_black_overline():
    blacks = [(2, 7), (3, 7), (4, 7), (6, 7), (7, 7), (5, 7)]  # шестёрка чёрных — не победа
    whites = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)]
    assert winning_line(interleave(blacks, whites)) is None


def test_winning_line_none_on_draw():
    blacks = [(x, y) for y in range(BOARD_SIZE) for x in range(BOARD_SIZE) if (x + 2 * y) % 4 < 2]
    whites = [(x, y) for y in range(BOARD_SIZE) for x in range(BOARD_SIZE) if (x + 2 * y) % 4 >= 2]
    assert winning_line(interleave(blacks, whites)) is None  # ничья — линии нет


def test_winning_line_double_closure_returns_first_direction():
    # (7,7) замыкает И горизонталь, И вертикаль; _DIRECTIONS начинает с (1,0) → горизонталь
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 3), (7, 4), (7, 5), (7, 6), (7, 7)]
    whites = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0), (12, 0), (14, 0)]
    line = winning_line(interleave(blacks, whites))
    assert line == [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]


def test_winning_line_empty_moves():
    assert winning_line([]) is None
