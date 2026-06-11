from app.domain.engine_params import EngineParams
from app.domain.opening import opening_zone
from app.rapfi.adapter import _move_commands

P = EngineParams(strength=50, timeout_turn_ms=1000)


def test_no_zone_is_plain_request():
    cmds = _move_commands([(7, 7)], P, None)
    assert "YXBLOCK" not in cmds and "YXBLOCKRESET" not in cmds
    assert cmds[-3:] == ["BOARD", "7,7,2", "DONE"]


def test_zone_brackets_position_with_block_and_reset():
    zone = opening_zone(1)  # 3×3
    cmds = _move_commands([(7, 7)], P, zone)
    assert cmds.index("YXBLOCK") < cmds.index("BOARD")  # блок до позиции
    assert cmds[-1] == "YXBLOCKRESET"  # снят хвостом
    # клетки 3×3 (кроме занятого центра) НЕ заблокированы; клетка вне зоны — заблокирована
    block_section = cmds[cmds.index("YXBLOCK") + 1 : cmds.index("DONE")]
    assert "8,8" not in block_section  # внутри 3×3 → свободна
    assert "7,7" not in block_section  # занята → не блокируем
    assert "0,0" in block_section  # вне зоны → блок


def test_empty_zone_raises():
    import pytest

    with pytest.raises(ValueError):
        _move_commands([(7, 7)], P, frozenset())
