import asyncio
from pathlib import Path

import pytest

from app.domain.levels import LEVELS, EngineParams, Level
from app.domain.values import BOARD_SIZE
from app.rapfi.adapter import EngineError, RapfiAdapter

FAST = EngineParams(strength=100, timeout_turn_ms=1000)


@pytest.fixture
async def adapter(rapfi_paths):
    bin_path, config_path, cwd = rapfi_paths
    a = RapfiAdapter(bin_path=bin_path, config_path=config_path, cwd=cwd)
    yield a
    await a.close()


def on_board(p):
    return 0 <= p[0] < BOARD_SIZE and 0 <= p[1] < BOARD_SIZE


async def test_compute_move_on_empty_board(adapter):
    move = await adapter.compute_move([], FAST)
    assert on_board(move)


async def test_compute_move_replies_to_human_move(adapter):
    move = await adapter.compute_move([(7, 7)], FAST)
    assert on_board(move)
    assert move != (7, 7)  # не в занятую клетку


async def test_state_isolation_between_requests(adapter):
    # партия A: 8 камней; затем партия B: 1 камень — ход для B не должен
    # учитывать камни A (т.е. может встать на клетку, занятую только в A)
    game_a = [(0, 0), (14, 14), (0, 1), (14, 13), (0, 2), (14, 12), (0, 3), (14, 11)]
    await adapter.compute_move(game_a, FAST)
    move_b = await adapter.compute_move([(7, 7)], FAST)
    assert on_board(move_b)
    assert move_b != (7, 7)


async def test_forbidden_points_on_double_three(adapter):
    # позиция проверена живым прогоном: двойная тройка чёрных в (7,7)
    moves = [(8, 7), (0, 0), (9, 7), (0, 2), (7, 8), (0, 4), (7, 9), (0, 6)]
    forbidden = await adapter.forbidden_points(moves)
    assert (7, 7) in forbidden


async def test_forbidden_points_empty_board(adapter):
    assert await adapter.forbidden_points([]) == []


async def test_forbidden_points_when_white_to_move_is_empty(adapter):
    # нечётное число камней — ход белых, у белых фолов нет; движок не дёргаем
    assert await adapter.forbidden_points([(7, 7)]) == []


async def test_recovers_after_engine_crash(adapter):
    await adapter.compute_move([], FAST)
    await adapter._proc.terminate(grace_s=0.1)  # имитация внешнего краха движка
    move = await adapter.compute_move([(7, 7)], FAST)  # respawn + повтор
    assert on_board(move)


async def test_hanging_engine_killed_by_wall_clock(rapfi_paths):
    _, config_path, cwd = rapfi_paths
    hang = Path(__file__).parent / "fixtures" / "hang_engine.sh"
    a = RapfiAdapter(bin_path=hang, config_path=config_path, cwd=cwd, wall_clock_slack_s=0.2)
    try:
        params = EngineParams(strength=100, timeout_turn_ms=200)
        with pytest.raises(EngineError):
            await a.compute_move([(7, 7)], params)
        assert a._proc is None or not a._proc.alive  # зависший процесс убит
    finally:
        await a.close()


async def test_concurrent_requests_serialized(adapter):
    moves = await asyncio.gather(
        adapter.compute_move([], FAST),
        adapter.compute_move([(7, 7)], FAST),
    )
    assert all(on_board(m) for m in moves)


async def test_real_levels_work_end_to_end(adapter):
    move = await adapter.compute_move([(7, 7)], LEVELS[Level.NOVICE])
    assert on_board(move)
