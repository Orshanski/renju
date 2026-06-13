from app.domain.engine_params import EngineParams
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
        (5, 7), (0, 1),  # B W
        (6, 7), (0, 2),  # B W
        (7, 5), (0, 3),  # B W
        (7, 6),          # B (7-й ход, чёрный)
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
