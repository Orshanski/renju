from app.domain.opening import CENTER, opening_zone


def test_center_is_h8():
    assert CENTER == (7, 7)


def test_move_zero_is_center_only():
    assert opening_zone(0) == frozenset({(7, 7)})


def test_move_one_is_central_3x3():
    zone = opening_zone(1)
    assert zone == frozenset((x, y) for x in range(6, 9) for y in range(6, 9))
    assert len(zone) == 9
    assert (6, 6) in zone and (8, 8) in zone
    assert (5, 7) not in zone and (9, 7) not in zone


def test_move_two_is_central_5x5():
    zone = opening_zone(2)
    assert zone == frozenset((x, y) for x in range(5, 10) for y in range(5, 10))
    assert len(zone) == 25
    assert (5, 5) in zone and (9, 9) in zone
    assert (4, 7) not in zone and (10, 7) not in zone


def test_move_three_and_beyond_unrestricted():
    assert opening_zone(3) is None
    assert opening_zone(10) is None
    assert opening_zone(224) is None
