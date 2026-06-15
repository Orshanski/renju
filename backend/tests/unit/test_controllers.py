from app.game.controllers import (
    engine_level_id,
    engine_level_tag,
    public_view,
    user_side,
)

# Реальная форма: ключ стороны = Color.value ("black"/"white"), см. service.py:141-143.
BLACK_HUMAN = {
    "black": {"kind": "user", "user_id": 7},
    "white": {"kind": "engine", "level_id": "master"},
}
BOTH_HUMAN = {
    "black": {"kind": "user", "user_id": 7},
    "white": {"kind": "user", "user_id": 9},
}


def test_engine_level_id_returns_level():
    assert engine_level_id(BLACK_HUMAN) == "master"


def test_engine_level_id_none_when_no_engine():
    assert engine_level_id(BOTH_HUMAN) is None


def test_engine_level_tag_returns_level_or_dash():
    assert engine_level_tag(BLACK_HUMAN) == "master"
    assert engine_level_tag(BOTH_HUMAN) == "-"


def test_user_side_finds_owner():
    assert user_side(BLACK_HUMAN, 7) == "black"
    assert user_side(BLACK_HUMAN, 999) is None


def test_public_view_hides_other_user_id_keeps_engine_level():
    assert public_view(BLACK_HUMAN) == {
        "black": {"kind": "user"},
        "white": {"kind": "engine", "levelId": "master"},
    }
