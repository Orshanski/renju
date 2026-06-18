import pytest

from app.domain.levels_depth import depth_ceiling


@pytest.mark.parametrize(
    "strength,expected",
    [
        (0, 4),
        (5, 4),
        (6, 4),
        (7, 5),
        (12, 5),
        (13, 6),
        (15, 6),
        (19, 6),
        (20, 7),
        (26, 7),
        (27, 8),
        (33, 8),
        (34, 9),
        (35, 9),
        (41, 9),
        (42, 10),
        (49, 10),
        (50, 11),
        (55, 11),
        (58, 11),
        (59, 12),
        (67, 12),
        (68, 13),
        (75, 13),
        (77, 13),
        (78, 14),
        (88, 14),
        (89, 15),
        (90, 15),
        (99, 15),
        (100, 16),
    ],
)
def test_depth_ceiling_matches_engine_formula(strength: int, expected: int):
    assert depth_ceiling(strength) == expected
