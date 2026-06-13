from app.domain.engine_params import EngineParams
from app.rapfi.registry import EngineRegistry

P = EngineParams(strength=5, timeout_turn_ms=1000)


def _reg(rapfi_paths):
    b, c, cwd = rapfi_paths
    return EngineRegistry(bin_path=b, config_path=c, cwd=cwd, idle_timeout_s=100.0)


async def test_distinct_games_distinct_pids(rapfi_paths):
    reg = _reg(rapfi_paths)
    try:
        await reg.compute_move("game-a", [(7, 7)], P)
        await reg.compute_move("game-b", [(7, 7)], P)
        # разные партии → разные процессы
        assert reg._slots["game-a"].pid != reg._slots["game-b"].pid
        await reg.compute_move("game-a", [(7, 7), (8, 8)], P)  # та же партия — тот же процесс
    finally:
        await reg.close()


async def test_engine_blocks_winning_four(rapfi_paths):
    """rj-t95-регрессия: на СВЕЖЕМ процессе движок закрывает открытую четвёрку белых."""
    reg = _reg(rapfi_paths)
    moves = [(7, 7), (8, 7), (8, 6), (9, 7), (6, 8), (9, 5), (9, 8), (10, 7), (7, 8), (11, 7)]
    try:
        mv = await reg.compute_move("g", moves, EngineParams(strength=5, timeout_turn_ms=1500))
        assert mv == (12, 7)
    finally:
        await reg.close()
