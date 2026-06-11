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
