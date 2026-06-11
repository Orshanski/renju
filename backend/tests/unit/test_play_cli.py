from scripts.play_cli import parse_input, render_board


def test_parse_input_letter_number():
    assert parse_input("h8") == (7, 7)
    assert parse_input("a1") == (0, 0)
    assert parse_input("o15") == (14, 14)
    assert parse_input("H8") == (7, 7)


def test_parse_input_invalid():
    for bad in ["", "z9", "h16", "h0", "88", "undo"]:
        assert parse_input(bad) is None


def test_render_board_smoke():
    out = render_board(moves=[(7, 7), (8, 8)], forbidden=[(0, 0)])
    assert "●" in out and "○" in out and "×" in out


def test_render_board_highlights_free_zone_cells():
    out = render_board(moves=[(7, 7)], forbidden=[], zone=frozenset({(8, 8), (7, 7)}))
    assert "+" in out  # (8,8) свободна и в зоне → подсветка
    # занятый центр (7,7) остаётся камнем, не "+"
    assert "●" in out


def test_render_board_no_zone_has_no_plus():
    out = render_board(moves=[(7, 7), (8, 8)], forbidden=[(0, 0)])
    assert "+" not in out
