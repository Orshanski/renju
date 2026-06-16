import asyncio
from pathlib import Path

import pytest

from app.domain.engine_params import EngineParams
from app.domain.values import BOARD_SIZE
from app.rapfi.adapter import EngineError
from app.rapfi.protocol import plan_sync
from app.rapfi.registry import EngineRegistry

P = EngineParams(strength=5, timeout_turn_ms=1000)


def _reg(rapfi_paths, tmp_path=None):
    import tempfile

    b, c, cwd = rapfi_paths
    data_dir = tmp_path if tmp_path is not None else Path(tempfile.mkdtemp())
    return EngineRegistry(
        bin_path=b, config_path=c, cwd=cwd, idle_timeout_s=100.0, data_dir=data_dir
    )


_DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]


def _made_five(stones: set[tuple[int, int]], last: tuple[int, int], *, exactly: bool) -> bool:
    """5 в ряд через last (та же геометрия, что в scripts/engine_probes). exactly=True
    (чёрные): ровно 5 — оверлайн не победа; иначе ≥5 (белые)."""
    for dx, dy in _DIRS:
        count = 1
        x, y = last
        while (x + dx, y + dy) in stones:
            count += 1
            x, y = x + dx, y + dy
        x, y = last
        while (x - dx, y - dy) in stones:
            count += 1
            x, y = x - dx, y - dy
        if (count == 5) if exactly else (count >= 5):
            return True
    return False


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
        assert reg._slots["g"].synced is not None
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


async def test_engine_white_holds_line_through_zone_and_undo(rapfi_paths):
    """Наше вождение (зона 3×3 + откат + повтор) не разваливает движок: движок-белый
    по-прежнему перехватывает простую чёрную линию.

    Перенос raw-пробы scripts/engine_probes/probe_black_line_zone_undo_raw.py на наш
    серверный путь (EngineRegistry: compute_move + allowed_zone + sync_after_undo).
    Проверяем СВОЙСТВО — чёрные не собрали пять (по геометрии made_five), а НЕ конкретный
    ход движка: его недетерминированную силу мы не тестируем. На этой тривиальной линии
    raw-проба держала 100/100 — значит провал тут = поломка нашего вождения, не движка.
    """
    from app.domain.opening import opening_zone

    line = [(7, 7), (8, 7), (9, 7), (10, 7), (11, 7)]  # человек ЧЁРНЫМИ тянет прямую
    params = EngineParams(strength=15, timeout_turn_ms=1000)
    zone = opening_zone(1)  # 3×3 на 1-й ход белых (RIF) — как YXBLOCK в пробе
    reg = _reg(rapfi_paths)
    try:
        # Фаза 1: построить до тройки чёрных; движок-белый отвечает (зона на 1-й ответ)
        moves: list[tuple[int, int]] = []
        for i, b in enumerate(line[:3]):
            if b in set(moves):  # движок занял клетку линии — дальше не строим
                break
            moves.append(b)
            e = await reg.compute_move("g", moves, params, zone if i == 0 else None)
            moves.append(e)

        # Фаза 2+3: откат до пустой доски + YXHASHCLEAR (наш sync_after_undo)
        await reg.sync_after_undo("g", [])
        assert reg._slots["g"].synced == []

        # Фаза 4: заново вся линия; перехват движка-белого — по геометрии
        moves = []
        black: set[tuple[int, int]] = set()
        white: set[tuple[int, int]] = set()
        conceded = False
        for i, b in enumerate(line):
            if b in white:  # движок-белый занял клетку линии → перехватил
                break
            black.add(b)
            moves.append(b)
            if _made_five(black, b, exactly=True):  # чёрные собрали 5 → движок СЛИЛ
                conceded = True
                break
            if i < len(line) - 1:
                e = await reg.compute_move("g", moves, params, zone if i == 0 else None)
                white.add(e)
                moves.append(e)
                if _made_five(white, e, exactly=False):  # белые сами собрали 5 → тоже перехват
                    break
        assert not conceded, (
            f"движок-белый слил тривиальную чёрную линию (поломка вождения?): {moves}"
        )
        assert reg._slots["g"].synced == moves  # вождение держит synced точно
    finally:
        await reg.close()


async def test_engine_black_holds_line_through_undo(rapfi_paths):
    """Наше вождение (откат + повтор) не разваливает движок: движок-чёрный по-прежнему
    перехватывает простую белую линию.

    Перенос raw-пробы scripts/engine_probes/probe_undo_raw.py на наш серверный путь
    (EngineRegistry: compute_move + sync_after_undo). Свойство по геометрии (белые не
    собрали пять), а не конкретный ход движка. Зоны нет — чёрного движка мы не обуздываем.
    """
    line = [(8, 7), (9, 7), (10, 7), (11, 7), (12, 7)]  # человек БЕЛЫМИ тянет прямую
    params = EngineParams(strength=15, timeout_turn_ms=1000)
    reg = _reg(rapfi_paths)
    try:
        # движок-чёрный ставит первый ход сам (свободно, как BEGIN в пробе)
        e1 = await reg.compute_move("g", [], params)
        moves: list[tuple[int, int]] = [e1]
        black: set[tuple[int, int]] = {e1}

        # Фаза 1: построить до тройки белых; движок-чёрный отвечает
        for w in line[:3]:
            if w in black:  # движок занял клетку линии до отката — мимо цели, не падаем
                break
            moves.append(w)
            e = await reg.compute_move("g", moves, params)
            black.add(e)
            moves.append(e)

        # Фаза 2+3: откат до первого хода + YXHASHCLEAR (наш sync_after_undo)
        await reg.sync_after_undo("g", [e1])
        assert reg._slots["g"].synced == [e1]

        # Фаза 4: заново вся белая линия; перехват движка-чёрного — по геометрии
        moves = [e1]
        black = {e1}
        white: set[tuple[int, int]] = set()
        conceded = False
        for i, w in enumerate(line):
            if w in black:  # движок-чёрный занял клетку линии → перехватил
                break
            white.add(w)
            moves.append(w)
            if _made_five(white, w, exactly=False):  # белые собрали 5 → движок СЛИЛ
                conceded = True
                break
            if i < len(line) - 1:
                e = await reg.compute_move("g", moves, params)
                black.add(e)
                moves.append(e)
                if _made_five(black, e, exactly=True):  # чёрные сами собрали 5 → перехват
                    break
        assert not conceded, (
            f"движок-чёрный слил тривиальную белую линию (поломка вождения?): {moves}"
        )
        assert reg._slots["g"].synced == moves
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


async def test_forbidden_points_cold_on_fresh_process(rapfi_paths):
    """Cold-форбид на СВЕЖЕМ процессе (synced=None, без предшествующего compute_move):
    _attempt_forbid сам шлёт START+правило (создают доску под YXBOARD), затем
    YXBOARD+YXSHOWFORBID. Движок распознаёт запрещённую точку — двойную тройку на (7,7).

    NB (rj-xv1): детект фола на ЖИВОМ движке проверяем ТОЛЬКО cold (все камни ставит тест,
    хода движка нет → позиция гарантирована). Warm-форбид (запрос на уже синхронизированной
    позиции) на живом движке отдельно НЕ тестируем: гарантировать фол там нельзя без
    гарантированного хода движка (движок сам может занять точку фола), а это недетерминизм =
    флак. Команды warm-форбида (только YXSHOWFORBID, без сброса synced) покрыты юнитом
    tests/unit/test_registry.py."""
    # позиция проверена живым прогоном: двойная тройка чёрных в (7,7)
    moves = [(8, 7), (0, 0), (9, 7), (0, 2), (7, 8), (0, 4), (7, 9), (0, 6)]
    reg = _reg(rapfi_paths)
    try:
        forbidden = await reg.forbidden_points("g", moves)  # cold, без прогрева
        assert (7, 7) in forbidden
        assert reg._slots["g"].synced == moves  # cold выставил synced
    finally:
        await reg.close()


async def test_forbidden_points_empty_board_fresh(rapfi_paths):
    """Пустая доска, свежий процесс: cold-форбид (START+YXBOARD пустой) → у чёрных фолов нет."""
    reg = _reg(rapfi_paths)
    try:
        assert await reg.forbidden_points("g", []) == []  # cold на свежем процессе
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
        assert slot.proc is not None
        await slot.proc.terminate(grace_s=0.1)
        # respawn + повтор должны произойти внутри следующего запроса
        move = await reg.compute_move("g", [(7, 7)], FAST)
        assert _on_board(move)
    finally:
        await reg.close()


async def test_hanging_engine_killed_by_wall_clock(rapfi_paths, tmp_path):
    """Зависший движок убивается по wall-clock и поднимает EngineError."""
    _, config_path, cwd = rapfi_paths
    hang = Path(__file__).parent / "fixtures" / "hang_engine.sh"
    reg = EngineRegistry(
        bin_path=hang,
        config_path=config_path,
        cwd=cwd,
        idle_timeout_s=100,
        wall_clock_slack_s=0.2,
        data_dir=tmp_path,
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
    zone1 = opening_zone(1)
    assert zone1 is not None
    try:
        move = await reg.compute_move("g", [(7, 7)], FAST, allowed_zone=zone1)
        assert move in zone1
        assert move != (7, 7)
    finally:
        await reg.close()


async def test_compute_move_in_5x5_zone(rapfi_paths):
    """Движок ходит внутри дебютной зоны 5×5 (opening_zone(2))."""
    from app.domain.opening import opening_zone

    reg = _reg(rapfi_paths)
    zone2 = opening_zone(2)
    assert zone2 is not None
    try:
        move = await reg.compute_move("g", [(7, 7), (8, 8)], FAST, allowed_zone=zone2)
        assert move in zone2
        assert move not in {(7, 7), (8, 8)}
    finally:
        await reg.close()


async def test_block_does_not_leak_to_next_request(rapfi_paths):
    """После дебютного запроса с зоной следующий TURN БЕЗ зоны не ограничен 5×5.

    Раньше тест подсовывал в тот же game_id несвязанную позицию, что требовало
    cold-reset живого процесса. Новый контракт: в живом процессе только TURN/TAKEBACK.
    """
    from app.domain.opening import opening_zone

    reg = _reg(rapfi_paths)
    try:
        first = await reg.compute_move("g", [(7, 7), (8, 8)], FAST, allowed_zone=opening_zone(2))
        target = [(7, 7), (8, 8), first, (0, 2)]  # следующий ход человека, уже вне дебюта
        move = await reg.compute_move("g", target, FAST)  # без зоны, через TURN 0,2
        assert move not in set(target)
    finally:
        await reg.close()


# ---------------------------------------------------------------------------
# B3c: тесты per-game конфига (assembled config)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nnue", [True, False])
async def test_engine_holds_line_under_assembled_config(rapfi_paths, tmp_path, nnue):
    """Движок держит линию под СГЕНЕРИРОВАННЫМ per-game конфигом (nnue=True и nnue=False).

    Проверяем свойство: движок-чёрный перехватывает простую белую линию при работе
    под per-game TOML (nnue=on — с нейросетью, nnue=off — только классика).
    Смысл: и в том и в другом режиме реестр собирает рабочий конфиг, процесс
    реально поднимается, и наше вождение (откат + повтор) его не ломает.

    Строим по образцу test_engine_black_holds_line_through_undo:
    движок-чёрный, человек-белый тянет линию [(8,7)…(12,7)].
    cwd=engine_dir, data_dir=tmp_path — чтобы относительные пути весов резолвились.
    """
    bin_path, base_config, _ = rapfi_paths
    engine_dir = base_config.parent
    reg = EngineRegistry(
        bin_path=bin_path,
        config_path=base_config,
        cwd=engine_dir,
        idle_timeout_s=100.0,
        data_dir=tmp_path,
    )
    line = [(8, 7), (9, 7), (10, 7), (11, 7), (12, 7)]  # человек БЕЛЫМИ тянет прямую
    params = EngineParams(strength=15, timeout_turn_ms=1000)
    try:
        # движок-чёрный ставит первый ход сам (свободно, как BEGIN в пробе)
        e1 = await reg.compute_move("g", [], params, nnue=nnue)
        moves: list[tuple[int, int]] = [e1]
        black: set[tuple[int, int]] = {e1}

        # Фаза 1: построить до тройки белых; движок-чёрный отвечает
        for w in line[:3]:
            if w in black:  # движок занял клетку линии — не ломаемся
                break
            moves.append(w)
            e = await reg.compute_move("g", moves, params, nnue=nnue)
            black.add(e)
            moves.append(e)

        # Фаза 2+3: откат до первого хода + YXHASHCLEAR (sync_after_undo)
        await reg.sync_after_undo("g", [e1])
        assert reg._slots["g"].synced == [e1]

        # Фаза 4: заново вся белая линия; перехват движка-чёрного — по геометрии
        moves = [e1]
        black = {e1}
        white: set[tuple[int, int]] = set()
        conceded = False
        for i, w in enumerate(line):
            if w in black:  # движок-чёрный занял клетку линии → перехватил
                break
            white.add(w)
            moves.append(w)
            if _made_five(white, w, exactly=False):  # белые собрали 5 → движок слил
                conceded = True
                break
            if i < len(line) - 1:
                e = await reg.compute_move("g", moves, params, nnue=nnue)
                black.add(e)
                moves.append(e)
                if _made_five(black, e, exactly=True):  # чёрные сами собрали 5 → перехват
                    break
        assert not conceded, (
            f"движок-чёрный слил тривиальную белую линию под assembled config "
            f"(nnue={nnue}, поломка вождения?): {moves}"
        )
    finally:
        await reg.close()


async def test_config_lifecycle_assemble_delete_regenerate(rapfi_paths, tmp_path):
    """Капстоун: полный жизненный цикл per-game конфига.

    Проверяем: файл собирается при входе (mark_present), удаляется при уходе
    последнего устройства (mark_absent), и пересобирается при возобновлении.
    mark_present спавнит синхронно: после await reg.mark_present(…) cfg_file уже
    существует (присутствие=1, слот поднят).
    """
    bin_path, base_config, _ = rapfi_paths
    engine_dir = base_config.parent
    game_id = "g"
    reg = EngineRegistry(
        bin_path=bin_path,
        config_path=base_config,
        cwd=engine_dir,
        idle_timeout_s=100.0,
        data_dir=tmp_path,
    )
    cfg_file = tmp_path / "engine_configs" / f"{game_id}.toml"
    try:
        # Шаг 2: ВХОД — поднять процесс с nnue=False; mark_present спавнит синхронно
        await reg.mark_present(game_id, nnue=False)
        assert cfg_file.exists(), "per-game TOML должен быть создан сразу после mark_present"

        # один ход — убедиться, что движок реально функционален под этим конфигом
        mv = await reg.compute_move(game_id, [(7, 7)], P, nnue=False)
        assert _on_board(mv) and mv != (7, 7), f"движок вернул нелегальный ход: {mv}"

        # Шаг 3: ОСТАНОВКА — mark_absent гасит процесс (presence: 1→0, inflight=0 → _terminate)
        await reg.mark_absent(game_id, reason="leave")
        assert not cfg_file.exists(), (
            "per-game TOML должен быть удалён при уходе последнего устройства"
        )
        assert game_id not in reg._slots, "слот должен быть изъят из реестра"

        # Шаг 4: ВОЗОБНОВЛЕНИЕ — новый вход; cfg_file должен быть пересобран
        await reg.mark_present(game_id, nnue=False)
        assert cfg_file.exists(), "per-game TOML должен быть пересобран при возобновлении"

        mv2 = await reg.compute_move(game_id, [(7, 7)], P, nnue=False)
        assert _on_board(mv2) and mv2 != (7, 7), (
            f"движок вернул нелегальный ход после возобновления: {mv2}"
        )
    finally:
        await reg.close()
