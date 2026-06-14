from app.domain.engine_params import EngineParams
from app.domain.opening import opening_zone
from app.rapfi.adapter import _move_commands, incremental_move_commands
from app.rapfi.protocol import SyncPlan

P = EngineParams(strength=50, timeout_turn_ms=1000)
P_INCR = EngineParams(strength=5, timeout_turn_ms=1000)


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


def test_incremental_no_zone_takeback_then_turn():
    plan = SyncPlan(cold=False, takebacks=((8, 8),), turn=(9, 9))
    cmds = incremental_move_commands(
        plan, target=[(7, 7), (9, 9)], params=P_INCR, allowed_zone=None
    )
    # YXHASHCLEAR после отката и ДО хода: снятый камень оставляет в TT стухшие
    # линии, иначе движок на возвращённой позиции отвечает не как на свежей.
    assert cmds == [
        "TAKEBACK 8,8",
        "YXHASHCLEAR",
        "INFO strength 5",
        "INFO timeout_turn 1000",
        "TURN 9,9",
    ]


def test_incremental_no_turn_uses_yxnbest_on_current_board():
    plan = SyncPlan(cold=False, takebacks=((5, 5), (6, 6), (8, 8)), turn=None)
    cmds = incremental_move_commands(plan, target=[(7, 7)], params=P_INCR, allowed_zone=None)
    assert cmds == [
        "TAKEBACK 5,5",
        "TAKEBACK 6,6",
        "TAKEBACK 8,8",
        "YXHASHCLEAR",
        "INFO strength 5",
        "INFO timeout_turn 1000",
        "YXNBEST 1",
    ]


def test_incremental_with_zone_wraps_turn():
    plan = SyncPlan(cold=False, takebacks=(), turn=(8, 8))
    target = [(7, 7), (8, 8)]
    cmds = incremental_move_commands(
        plan, target=target, params=P_INCR, allowed_zone=opening_zone(2)
    )
    assert cmds[0] == "INFO strength 5"
    assert "YXHASHCLEAR" not in cmds  # ход вперёд без отката — тёплую TT не чистим
    assert cmds.count("YXBLOCK") == 1 and cmds[-1] == "YXBLOCKRESET"
    assert "TURN 8,8" in cmds
    block_idx = cmds.index("YXBLOCK")
    done_idx = cmds.index("DONE")
    assert "8,8" not in cmds[block_idx:done_idx]  # клетка хода человека ∈ target → не в блоке
