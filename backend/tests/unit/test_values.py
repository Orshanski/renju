from app.domain.values import (
    BOARD_SIZE,
    MAX_MOVES,
    Color,
    GameStatus,
    color_of_move,
    color_to_move,
)


def test_board_constants():
    assert BOARD_SIZE == 15
    assert MAX_MOVES == 225


def test_color_of_move_alternates_from_black():
    assert color_of_move(0) is Color.BLACK
    assert color_of_move(1) is Color.WHITE
    assert color_of_move(224) is Color.BLACK


def test_color_to_move_by_move_count():
    assert color_to_move(0) is Color.BLACK   # пустая доска — ходят чёрные
    assert color_to_move(1) is Color.WHITE
    assert color_to_move(8) is Color.BLACK


def test_game_status_values_match_spec_enum():
    # значения попадут в БД и API (этапы 2–3) — фиксируем строки спека §4.3
    assert GameStatus.AWAITING_HUMAN.value == "awaiting_human"
    assert GameStatus.ENGINE_THINKING.value == "engine_thinking"
    assert GameStatus.FINISHED_BLACK.value == "finished_black"
    assert GameStatus.FINISHED_WHITE.value == "finished_white"
    assert GameStatus.FINISHED_DRAW.value == "finished_draw"
    assert GameStatus.FINISHED_BLACK.is_finished
    assert not GameStatus.AWAITING_HUMAN.is_finished
