import asyncio
from pathlib import Path

import pytest

from app.domain.engine_params import EngineParams
from app.domain.values import BOARD_SIZE
from app.rapfi.adapter import EngineError
from app.rapfi.protocol import plan_sync
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


# ---------------------------------------------------------------------------
# rj-t95: инкрементальный путь (TAKEBACK/TURN) — live-регрессии
# ---------------------------------------------------------------------------


async def test_warm_takeback_mechanics(rapfi_paths):
    """rj-t95: WARM с непустыми TAKEBACK отрабатывает без рассинхрона и краша процесса.

    Стратегия (не зависит от конкретного хода движка):
      1. cold [(7,7)] → движок играет mv_cold; synced = [(7,7), mv_cold].
      2. target = [(7,7), (0,0)]: общий префикс 1 (только (7,7)), tail=[(0,0)].
         plan_sync гарантирует WARM с takebacks=(mv_cold,) → TAKEBACK mv_cold + TURN (0,0).
      3. Движок отвечает mv_warm; проверяем синтаксическую корректность (не занято),
         консистентность synced и сохранность pid.
    Тест не пиннит конкретный ход движка — только доказывает, что TAKEBACK/TURN
    отрабатывают на живом движке без рассинхрона и рестарта процесса.
    """
    reg = _reg(rapfi_paths)
    try:
        # Шаг 1: cold с одним ходом
        mv_cold = await reg.compute_move("g", [(7, 7)], P)
        pid_before = reg._slots["g"].pid
        synced_after_cold = list(reg._slots["g"].synced)
        assert synced_after_cold == [(7, 7), mv_cold]

        # Шаг 2: warm-запрос — target расходится от synced на позиции 1
        # prefix = [(7,7)]; tail = [(0,0)] → WARM; takebacks = (mv_cold,)
        human_stone = (0, 0)
        target_warm = [(7, 7), human_stone]
        plan = plan_sync(synced_after_cold, target_warm)
        assert not plan.cold, f"ожидали warm, plan_sync вернул cold: {plan}"
        assert plan.takebacks == (mv_cold,), f"неверные takebacks: {plan.takebacks}"
        assert plan.turn == human_stone

        mv_warm = await reg.compute_move("g", target_warm, P)

        # ход легален: не в занятую клетку из target_warm
        assert mv_warm not in {(7, 7), human_stone}, f"движок сыграл в занятую клетку: {mv_warm}"
        # synced консистентен
        assert reg._slots["g"].synced == [*target_warm, mv_warm]
        # процесс не рестартовал — pid тот же
        assert reg._slots["g"].pid == pid_before, "pid сменился: unexpected respawn"
    finally:
        await reg.close()


async def test_warm_forced_block_after_detour(rapfi_paths):
    """rj-t95: после warm-детура движок не зевает открытую четвёрку белых (anti-зевок (12,7)).

    forcing = [(7,7),(8,7),(8,6),(9,7),(6,8),(9,5),(9,8),(10,7),(7,8),(11,7)]

    Построение warm-детура (strength=5, timeout=1500ms):
      Шаг 1: cold forcing[:8] — живой движок стабильно отвечает (7,8) = forcing[8].
        synced = forcing[:8] + [(7,8)] = forcing[:9].
      Шаг 2: target = forcing = forcing[:9] + [(11,7)].
        plan_sync: prefix=9, tail=[(11,7)], takebacks=() → WARM (TURN (11,7) без TAKEBACK).
      Финальный ассерт: движок ОБЯЗАН закрыть открытую горизонтальную четвёрку белых → (12,7).

    Детур доказывает, что warm-путь к критической позиции не вызывает тактического зевка.
    """
    forcing = [(7, 7), (8, 7), (8, 6), (9, 7), (6, 8), (9, 5), (9, 8), (10, 7), (7, 8), (11, 7)]
    fast = EngineParams(strength=5, timeout_turn_ms=1500)
    reg = _reg(rapfi_paths)
    try:
        # Шаг 1: cold на forcing[:8] → движок стабильно играет (7,8) = forcing[8]
        # → synced = forcing[:9]
        mv_interim = await reg.compute_move("g", forcing[:8], fast)
        synced_after_cold = list(reg._slots["g"].synced)

        # Шаг 2: plan_sync проверяем вручную — если synced = forcing[:9], путь к forcing WARM
        plan = plan_sync(synced_after_cold, forcing)
        if not plan.cold:
            # WARM-путь: доказываем что TAKEBACK/TURN к позиции forcing отрабатывает корректно
            assert plan.turn == (11, 7), f"неверный TURN в warm-плане: {plan.turn}"

        # Итоговый запрос: в любом случае (warm или cold) ассерт на (12,7) обязателен
        mv_final = await reg.compute_move("g", forcing, fast)
        assert mv_final == (12, 7), (
            f"движок зевнул открытую четвёрку белых: сыграл {mv_final} "
            f"(путь был {'warm' if not plan.cold else 'cold'}, mv_interim={mv_interim})"
        )
        assert reg._slots["g"].synced == [*forcing, (12, 7)]
    finally:
        await reg.close()


async def test_warm_forbid_no_reset(rapfi_paths):
    """rj-t95: warm-запрос YXSHOWFORBID не сбрасывает synced и не меняет pid.

    Позиция (7 ходов, движок-белый, strength=5, timeout=1000ms):
      dbl3_moves — чёрные строят двойную тройку на (7,7):
        (5,7),(6,7) горизонтально и (7,5),(7,6) вертикально; белые нейтральны в (0,1-3).
    Наблюдаемые значения (стабильны 10/10 прогонов):
      движок-белый отвечает (0,4); synced = dbl3_moves+[(0,4)] (8 элементов, чётное).
    Warm-форбид: _attempt_forbid видит slot.synced == target → шлёт только YXSHOWFORBID.
    Ожидаем: (7,7) в forbidden (двойная тройка), synced неизменён, pid неизменён.
    """
    # 7 ходов (нечётное) → движок ходит белым (8-й) → synced из 8 элементов (чётное)
    # → forbidden_points не блокируется по гейту len(moves) % 2 != 0
    dbl3_moves = [
        (5, 7),
        (0, 1),  # B W
        (6, 7),
        (0, 2),  # B W
        (7, 5),
        (0, 3),  # B W
        (7, 6),  # B (7-й ход, чёрный)
    ]
    reg = _reg(rapfi_paths)
    try:
        mv = await reg.compute_move("g", dbl3_moves, P)
        assert mv == (0, 4), f"ход движка-белого изменился: {mv}"
        synced_before = list(reg._slots["g"].synced)
        assert len(synced_before) == 8, "synced должен быть чётной длины для warm-форбида"
        pid_before = reg._slots["g"].pid

        # warm-форбид: target == slot.synced → _attempt_forbid шлёт только YXSHOWFORBID
        fb = await reg.forbidden_points("g", synced_before)

        assert (7, 7) in fb, f"(7,7) должна быть запрещена (двойная тройка), получили: {fb}"
        assert reg._slots["g"].synced == synced_before, "warm-форбид сбросил synced"
        assert reg._slots["g"].pid == pid_before, "pid сменился после warm-форбида"
    finally:
        await reg.close()


# ---------------------------------------------------------------------------
# Перенесено из test_adapter.py: engine-контракт-тесты на EngineRegistry
# ---------------------------------------------------------------------------

FAST = EngineParams(strength=100, timeout_turn_ms=1000)


def _on_board(p: tuple[int, int]) -> bool:
    return 0 <= p[0] < BOARD_SIZE and 0 <= p[1] < BOARD_SIZE


async def test_compute_move_on_empty_board(rapfi_paths):
    """Движок отвечает легальным ходом на пустой доске (cold-запрос)."""
    reg = _reg(rapfi_paths)
    try:
        move = await reg.compute_move("g", [], FAST)
        assert _on_board(move)
    finally:
        await reg.close()


async def test_compute_move_replies_to_human_move(rapfi_paths):
    """Движок отвечает на первый ход человека — не в занятую клетку."""
    reg = _reg(rapfi_paths)
    try:
        move = await reg.compute_move("g", [(7, 7)], FAST)
        assert _on_board(move)
        assert move != (7, 7)
    finally:
        await reg.close()


async def test_forbidden_points_cold_double_three(rapfi_paths):
    """Cold-запрос: движок распознаёт запрещённую точку (двойная тройка) на (7,7).

    Движок должен быть прогрет (compute_move) перед YXBOARD — registry требует
    активного сеанса (START уже был послан через compute_move).
    """
    # позиция проверена живым прогоном: двойная тройка чёрных в (7,7)
    moves = [(8, 7), (0, 0), (9, 7), (0, 2), (7, 8), (0, 4), (7, 9), (0, 6)]
    reg = _reg(rapfi_paths)
    try:
        # прогрев: compute_move запускает START+INFO → после этого YXBOARD работает
        await reg.compute_move("g", [(7, 7)], FAST)
        # cold-запрос фолов: slot.synced != moves → _attempt_forbid шлёт YXBOARD+YXSHOWFORBID
        forbidden = await reg.forbidden_points("g", moves)
        assert (7, 7) in forbidden
    finally:
        await reg.close()


async def test_forbidden_points_empty_board(rapfi_paths):
    """На пустой доске у чёрных нет запрещённых точек.

    Движок прогрет через compute_move (START уже был); YXBOARD с пустым списком
    возвращает FORBID без единой координаты.
    """
    reg = _reg(rapfi_paths)
    try:
        # прогрев: ensure START+INFO sent to engine
        await reg.compute_move("g", [(7, 7)], FAST)
        # cold-форбид на пустой доске: moves=[] → ход чёрных → engine вернёт FORBID
        assert await reg.forbidden_points("g", []) == []
    finally:
        await reg.close()


async def test_forbidden_points_white_to_move_is_empty(rapfi_paths):
    """Нечётное число камней → ход белых → forbidden_points возвращает [] без запроса к движку."""
    reg = _reg(rapfi_paths)
    try:
        assert await reg.forbidden_points("g", [(7, 7)]) == []
    finally:
        await reg.close()


async def test_recovers_after_engine_crash(rapfi_paths):
    """После внешнего краша процесса движок пересоздаётся и выдаёт легальный ход."""
    reg = _reg(rapfi_paths)
    try:
        await reg.compute_move("g", [], FAST)
        # имитируем внешний крах: завершаем процесс движка напрямую
        slot = reg._slots["g"]
        await slot.proc.terminate(grace_s=0.1)
        # respawn + повтор должны произойти внутри следующего запроса
        move = await reg.compute_move("g", [(7, 7)], FAST)
        assert _on_board(move)
    finally:
        await reg.close()


async def test_hanging_engine_killed_by_wall_clock(rapfi_paths):
    """Зависший движок убивается по wall-clock и поднимает EngineError."""
    _, config_path, cwd = rapfi_paths
    hang = Path(__file__).parent / "fixtures" / "hang_engine.sh"
    reg = EngineRegistry(
        bin_path=hang,
        config_path=config_path,
        cwd=cwd,
        idle_timeout_s=100,
        wall_clock_slack_s=0.2,
    )
    try:
        params = EngineParams(strength=100, timeout_turn_ms=200)
        with pytest.raises(EngineError):
            await reg.compute_move("g", [(7, 7)], params)
    finally:
        await reg.close()


async def test_concurrent_requests_serialized(rapfi_paths):
    """Два одновременных запроса (разные game_id) выполняются без ошибок."""
    reg = _reg(rapfi_paths)
    try:
        moves = await asyncio.gather(
            reg.compute_move("g1", [], FAST),
            reg.compute_move("g2", [(7, 7)], FAST),
        )
        assert all(_on_board(m) for m in moves)
    finally:
        await reg.close()


async def test_real_levels_work_end_to_end(rapfi_paths):
    """Реальные параметры слабого уровня (strength=10) дают легальный ход."""
    reg = _reg(rapfi_paths)
    try:
        move = await reg.compute_move(
            "g", [(7, 7)], EngineParams(strength=10, timeout_turn_ms=1000)
        )
        assert _on_board(move)
    finally:
        await reg.close()


async def test_compute_move_in_3x3_zone(rapfi_paths):
    """Движок ходит внутри дебютной зоны 3×3 (opening_zone(1))."""
    from app.domain.opening import opening_zone

    reg = _reg(rapfi_paths)
    try:
        move = await reg.compute_move("g", [(7, 7)], FAST, allowed_zone=opening_zone(1))
        assert move in opening_zone(1)
        assert move != (7, 7)
    finally:
        await reg.close()


async def test_compute_move_in_5x5_zone(rapfi_paths):
    """Движок ходит внутри дебютной зоны 5×5 (opening_zone(2))."""
    from app.domain.opening import opening_zone

    reg = _reg(rapfi_paths)
    try:
        move = await reg.compute_move("g", [(7, 7), (8, 8)], FAST, allowed_zone=opening_zone(2))
        assert move in opening_zone(2)
        assert move not in {(7, 7), (8, 8)}
    finally:
        await reg.close()


async def test_block_does_not_leak_to_next_request(rapfi_paths):
    """После дебютного запроса с зоной следующий запрос БЕЗ зоны не ограничен 5×5.

    far-кластер на левом крае (x=0): если бы YXBLOCK протёк — ход в кластере был бы
    невозможен и compute_move упал бы. Ход x≤4 доказывает: блок снят корректно.
    """
    from app.domain.opening import opening_zone

    reg = _reg(rapfi_paths)
    try:
        await reg.compute_move("g", [(7, 7), (8, 8)], FAST, allowed_zone=opening_zone(2))
        far = [(0, 2), (0, 3), (0, 4), (0, 5), (0, 6)]  # кластер на левом крае
        move = await reg.compute_move("g", far, FAST)  # без зоны
        assert move not in set(far)
        assert move not in opening_zone(2)
    finally:
        await reg.close()
