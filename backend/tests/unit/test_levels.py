import pytest

from app.domain.levels import LEVELS, Level


def test_all_levels_have_params():
    assert set(LEVELS) == set(Level)


def test_strength_in_engine_range_and_monotonic():
    ordered = [Level.NOVICE, Level.EASY, Level.MEDIUM, Level.HARD, Level.MASTER]
    strengths = [LEVELS[lv].strength for lv in ordered]
    assert all(0 <= s <= 100 for s in strengths)
    assert strengths == sorted(strengths)
    assert strengths[-1] == 100  # master — без ослабления


def test_timeouts_positive():
    assert all(p.timeout_turn_ms > 0 for p in LEVELS.values())


def test_params_immutable():
    with pytest.raises(AttributeError):
        LEVELS[Level.NOVICE].strength = 99  # type: ignore[misc]
