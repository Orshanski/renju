# Инкрементальное управление движком Rapfi — план реализации (rj-t95)

> **For agentic workers:** REQUIRED SUB-SKILL: используй superpowers:subagent-driven-development (рекоменд.) или superpowers:executing-plans для пошагового выполнения. Шаги — чекбоксы (`- [ ]`).

**Goal:** Гонять Rapfi инкрементально (`TURN`/`TAKEBACK`, `START`/`BOARD` только на холодную синхронизацию свежего процесса), чтобы движок не деградировал после undo.

**Architecture:** Per-game процесс (rj-899) держит инкрементальное состояние. `EngineSlot` трекает `synced` (позицию в движке); `EngineRegistry` приводит её к нужной диффом (`TAKEBACK` до общего префикса + один `TURN`), строя команды от `slot.synced` под `io_lock`. Чистый планировщик/сборщики команд — в `protocol.py`. Спека: `docs/superpowers/specs/2026-06-13-incremental-engine-driving-design.md`.

**Tech Stack:** Python 3.13 / asyncio / pytest. Движок Rapfi (Piskvork-протокол, stdin/stdout).

---

## Структура файлов

- `backend/app/rapfi/protocol.py` (**править**) — чистые: `tunable_commands`, `turn_commands`, `takeback_commands`, `SyncPlan`, `plan_sync`. `init_commands` рефактор: `= start + tunable`.
- `backend/app/rapfi/adapter.py` (**править**) — удалить класс `RapfiAdapter`; оставить `EngineError`, константы, `_move_commands` (cold-builder); добавить `incremental_move_commands` (warm-builder) + общий `_zone_block`.
- `backend/app/rapfi/registry.py` (**править**) — `EngineSlot.synced`; `_run`/`_attempt` строят дельту от `synced` под `io_lock`, обновляют `synced`; `compute_move`/`forbidden_points` передают намерение; сброс `synced` на respawn и пост-лок отказе.
- `backend/app/game/service.py` (**править**) — `advance`: фолы для стороны-движка не запрашивать (`forbidden=[]`).
- Удалить: `backend/scripts/play_cli.py`, `backend/tests/unit/test_play_cli.py`, `backend/tests/integration/test_adapter.py`. Класс `RapfiAdapter` из `adapter.py`.
- `CLAUDE.md (корень репо)` (**править**) — убрать строку запуска `play_cli` из §Команды.
- `backend/tests/integration/test_games_live.py:2` (**править**) — комментарий `RapfiAdapter` → `EngineRegistry`.
- `backend/tests/integration/test_registry_live.py` (**править**) — перенести engine-контракт-тесты из `test_adapter.py` (фолы, дебют-зона, block-no-leak, wall-clock kill, recovery, real-levels) + новые регресс-тесты undo/warm-forbid. Fixture `tests/integration/fixtures/hang_engine.sh` — сохранить.

---

## Task 1: protocol.py — чистый планировщик и сборщики команд

**Files:**
- Modify: `backend/app/rapfi/protocol.py`
- Test: `backend/tests/unit/test_protocol.py` (существует), либо новый `test_sync_plan.py`

- [ ] **Step 1: Failing-тест планировщика и сборщиков**

В `backend/tests/unit/test_protocol.py` добавить:

```python
from app.rapfi.protocol import (
    SyncPlan, plan_sync, tunable_commands, turn_commands, takeback_commands,
)
from app.domain.engine_params import EngineParams


def test_plan_sync_cold_when_synced_none():
    assert plan_sync(None, [(7, 7), (8, 8)]) == SyncPlan(cold=True, takebacks=(), turn=(8, 8)) or \
        plan_sync(None, [(7, 7), (8, 8)]).cold  # cold: turn/takebacks игнорируются


def test_plan_sync_forward_single_turn():
    synced = [(7, 7), (6, 6), (8, 8)]            # движок сходил (8,8)
    target = [(7, 7), (6, 6), (8, 8), (9, 9)]    # человек добавил (9,9)
    assert plan_sync(synced, target) == SyncPlan(cold=False, takebacks=(), turn=(9, 9))


def test_plan_sync_undo_then_move_takes_back_to_prefix():
    synced = [(7, 7), (6, 6), (8, 8)]            # движок на 3 камнях
    target = [(7, 7), (9, 9)]                    # откат к 1 + новый ход (9,9)
    # общий префикс = [(7,7)]; снять (8,8),(6,6) с хвоста, затем TURN (9,9)
    assert plan_sync(synced, target) == SyncPlan(cold=False, takebacks=((8, 8), (6, 6)), turn=(9, 9))


def test_plan_sync_anomaly_tail_zero_is_cold():
    synced = [(7, 7), (8, 8), (9, 9)]
    target = [(7, 7), (8, 8)]                    # target — строгий префикс synced → tail=0
    assert plan_sync(synced, target).cold


def test_plan_sync_anomaly_tail_gt_one_is_cold():
    synced = [(7, 7)]
    target = [(7, 7), (8, 8), (9, 9)]            # tail=2 → аномалия
    assert plan_sync(synced, target).cold


def test_tunable_commands_per_move_info():
    assert tunable_commands(EngineParams(strength=7, timeout_turn_ms=1500)) == [
        "INFO strength 7", "INFO timeout_turn 1500",
    ]


def test_turn_command_format():
    assert turn_commands((8, 7)) == ["TURN 8,7"]


def test_takeback_commands_format_and_order():
    # принимает координаты в порядке отправки (хвост synced, развёрнутый)
    assert takeback_commands([(9, 9), (6, 6)]) == ["TAKEBACK 9,9", "TAKEBACK 6,6"]


def test_takeback_commands_validates_coords():
    import pytest
    from app.rapfi.protocol import ProtocolError
    with pytest.raises(ProtocolError):
        takeback_commands([(15, 0)])  # вне доски — анти-инъекция (спек §5.2)
```

- [ ] **Step 2: Прогнать — упадёт (нет символов)**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_protocol.py -k "plan_sync or tunable or turn_command or takeback" -v`
Expected: FAIL (ImportError / NameError).

- [ ] **Step 3: Реализация в `protocol.py`**

Добавить импорт `from dataclasses import dataclass` (если нет) и:

```python
@dataclass(frozen=True)
class SyncPlan:
    """Как привести движок от synced к target ДЛЯ ЗАПРОСА ХОДА (compute_move).
    cold=True → послать START+INFO+BOARD(target), сбросив состояние; иначе —
    takebacks (координаты снимаемых камней, в порядке отправки) + один TURN."""
    cold: bool
    takebacks: tuple[Point, ...]
    turn: Point | None


def plan_sync(synced: Sequence[Point] | None, target: Sequence[Point]) -> SyncPlan:
    if synced is None:
        return SyncPlan(cold=True, takebacks=(), turn=None)
    n = 0
    while n < len(synced) and n < len(target) and tuple(synced[n]) == tuple(target[n]):
        n += 1
    tail = list(target[n:])
    if len(tail) != 1:  # 0 (target⊆synced) или >1 (разрыв) — оба в cold (§4.2 аномалия)
        return SyncPlan(cold=True, takebacks=(), turn=None)
    takebacks = tuple(tuple(p) for p in reversed(list(synced[n:])))  # снять хвост с конца
    return SyncPlan(cold=False, takebacks=takebacks, turn=tuple(tail[0]))


def tunable_commands(params: EngineParams) -> list[str]:
    """Per-move INFO (сила/время). Шлём перед каждым расчётом (§3.1)."""
    return [f"INFO strength {params.strength}", f"INFO timeout_turn {params.timeout_turn_ms}"]


def turn_commands(point: Point) -> list[str]:
    _validate_moves([point])
    x, y = point
    return [f"TURN {x},{y}"]


def takeback_commands(points: Sequence[Point]) -> list[str]:
    """TAKEBACK x,y на каждый снимаемый камень (формат снят с gomocup.cpp:586 —
    движок читает x,y и игнорирует, откатывая последний ход). Голый TAKEBACK
    запрещён: движок завис бы на cin>>x."""
    _validate_moves(points)
    return [f"TAKEBACK {x},{y}" for x, y in points]
```

Рефактор `init_commands` (поведение неизменно — cold по-прежнему шлёт все 4 строки):

```python
def init_commands(params: EngineParams) -> list[str]:
    """Холодная инициализация: START + правило (инварианты процесса) + tunable."""
    return [f"START {BOARD_SIZE}", "INFO rule 4", *tunable_commands(params)]
```

- [ ] **Step 4: Прогнать — зелено**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_protocol.py -v`
Expected: PASS (включая существующие тесты `init_commands` — поведение то же).

- [ ] **Step 5: Commit**

```bash
git add backend/app/rapfi/protocol.py backend/tests/unit/test_protocol.py
git commit -m "feat(rj-t95): protocol — sync-планировщик + TURN/TAKEBACK/tunable-команды"
```

---

## Task 2: adapter.py — warm-сборщик + общий блок-хелпер; класс RapfiAdapter удалить позже

**Files:**
- Modify: `backend/app/rapfi/adapter.py`
- Test: `backend/tests/unit/test_adapter_commands.py`

- [ ] **Step 1: Failing-тест warm-сборщика**

В `backend/tests/unit/test_adapter_commands.py` добавить:

```python
from app.rapfi.adapter import incremental_move_commands
from app.rapfi.protocol import SyncPlan
from app.domain.engine_params import EngineParams
from app.domain.opening import opening_zone

P = EngineParams(strength=5, timeout_turn_ms=1000)


def test_incremental_no_zone_takeback_then_turn():
    plan = SyncPlan(cold=False, takebacks=((8, 8),), turn=(9, 9))
    cmds = incremental_move_commands(plan, target=[(7, 7), (9, 9)], params=P, allowed_zone=None)
    assert cmds == ["TAKEBACK 8,8", "INFO strength 5", "INFO timeout_turn 1000", "TURN 9,9"]


def test_incremental_with_zone_wraps_turn():
    plan = SyncPlan(cold=False, takebacks=(), turn=(8, 8))
    target = [(7, 7), (8, 8)]
    cmds = incremental_move_commands(plan, target=target, params=P, allowed_zone=opening_zone(2))
    assert cmds[0] == "INFO strength 5"
    assert cmds.count("YXBLOCK") == 1 and cmds[-1] == "YXBLOCKRESET"
    assert "TURN 8,8" in cmds
    # клетка хода человека (8,8) ∈ target → НЕ в блоке
    block_idx = cmds.index("YXBLOCK"); done_idx = cmds.index("DONE")
    assert "8,8" not in cmds[block_idx:done_idx]
```

- [ ] **Step 2: Прогнать — упадёт**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_adapter_commands.py -k incremental -v`
Expected: FAIL (нет `incremental_move_commands`).

- [ ] **Step 3: Реализация в `adapter.py`**

Извлечь блок-хелпер из `_move_commands` и добавить warm-сборщик:

```python
def _zone_block(moves: Sequence[Point], allowed_zone: frozenset[Point] | None) -> list[str]:
    """YXBLOCK-блок: все свободные клетки вне зоны. [] если зоны нет."""
    if allowed_zone is None:
        return []
    if not allowed_zone:
        raise ValueError("allowed_zone must be None or non-empty")
    occupied = set(moves)
    block = [
        (x, y)
        for x in range(BOARD_SIZE)
        for y in range(BOARD_SIZE)
        if (x, y) not in allowed_zone and (x, y) not in occupied
    ]
    return block_commands(block)


def incremental_move_commands(
    plan: SyncPlan,
    *,
    target: Sequence[Point],
    params: EngineParams,
    allowed_zone: frozenset[Point] | None,
) -> list[str]:
    """Тёплый ход: TAKEBACK(хвост) → per-move INFO → [YXBLOCK]→TURN→[YXBLOCKRESET].
    Зона берётся от позиции target (клетка хода человека ∈ target → не блокируется)."""
    assert not plan.cold and plan.turn is not None
    block = _zone_block(target, allowed_zone)
    cmds = [*takeback_commands(plan.takebacks), *tunable_commands(params), *block, *turn_commands(plan.turn)]
    if block:
        cmds.append("YXBLOCKRESET")
    return cmds
```

`_move_commands` (cold-builder) переписать через `_zone_block` (поведение неизменно):

```python
def _move_commands(moves, params, allowed_zone):
    """COLD: init(START+INFO) + [YXBLOCK] + BOARD(moves) + [YXBLOCKRESET]."""
    commands = init_commands(params)
    block = _zone_block(moves, allowed_zone)
    commands += block + position_commands(moves)
    if block:
        commands += ["YXBLOCKRESET"]
    return commands
```

(Импортировать `SyncPlan`, `tunable_commands`, `takeback_commands`, `turn_commands` из `.protocol`.)

- [ ] **Step 4: Прогнать — зелено** (включая существующие тесты `_move_commands`)

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_adapter_commands.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rapfi/adapter.py backend/tests/unit/test_adapter_commands.py
git commit -m "feat(rj-t95): adapter — warm-сборщик ходов + общий zone-block"
```

---

## Task 3: registry.py — инкремент в _run/_attempt, трекинг synced

**Files:**
- Modify: `backend/app/rapfi/registry.py`
- Test: `backend/tests/unit/test_registry.py` (FakeProc-механика)

- [ ] **Step 1: Failing-тесты на FakeProc** (проверяем посланные команды и synced)

В `backend/tests/unit/test_registry.py` добавить (используем СУЩЕСТВУЮЩИЕ `FakeProc(script)`
— `proc.sent` копит списки посланных строк, `script` = ответы `read_line` — и `make_registry(spawn)`,
`P = EngineParams(50, 200)`; своих хелперов НЕ выдумываем):

```python
@pytest.mark.asyncio
async def test_first_move_cold_board_sets_synced():
    procs = []
    async def spawn(**kw):
        p = FakeProc(["8,8"]); procs.append(p); return p
    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    sent = [c for batch in procs[0].sent for c in batch]
    assert "START 15" in sent and "BOARD" in sent
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]   # target + ход движка
    await reg.close()


@pytest.mark.asyncio
async def test_second_move_incremental_turn_no_newgame():
    procs = []
    async def spawn(**kw):
        p = FakeProc(["8,8", "5,5"]); procs.append(p); return p  # один процесс, два хода
    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)                      # cold → synced=[(7,7),(8,8)]
    procs[0].sent.clear()
    await reg.compute_move("g", [(7, 7), (8, 8), (6, 6)], P)      # человек добавил (6,6)
    sent = [c for batch in procs[0].sent for c in batch]
    assert "START 15" not in sent and "TURN 6,6" in sent         # инкремент, не newGame
    assert reg._slots["g"].synced == [(7, 7), (8, 8), (6, 6), (5, 5)]
    await reg.close()


@pytest.mark.asyncio
async def test_undo_path_takeback_to_prefix_then_turn():
    procs = []
    async def spawn(**kw):
        p = FakeProc(["8,8", "4,4"]); procs.append(p); return p
    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7), (6, 6)], P)             # cold → synced=[(7,7),(6,6),(8,8)]
    procs[0].sent.clear()
    await reg.compute_move("g", [(7, 7), (9, 9)], P)            # откат к [(7,7)] + ход (9,9)
    sent = [c for batch in procs[0].sent for c in batch]
    assert sent.count("START 15") == 0
    assert "TAKEBACK 8,8" in sent and "TAKEBACK 6,6" in sent and "TURN 9,9" in sent
    assert reg._slots["g"].synced == [(7, 7), (9, 9), (4, 4)]
    await reg.close()
```

- [ ] **Step 2: Прогнать — упадёт**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_registry.py -k "cold_board or incremental_turn or takeback_to_prefix" -v`
Expected: FAIL.

- [ ] **Step 3: Реализация — `EngineSlot.synced` + рефактор `_run`/`_attempt`**

В `EngineSlot` добавить поле:

```python
    synced: list[Point] | None = None  # позиция в движке (вкл. его ход); None = свежий процесс
```

`_respawn` и `_spawn_into`: при установке нового `slot.proc` выставлять `slot.synced = None`.

Ввести намерение и перестроить расчётный путь. `compute_move` и `forbidden_points` больше НЕ предвычисляют `commands` — передают намерение в `_run`:

```python
async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
    target = [tuple(m) for m in moves]
    timeout = params.timeout_turn_ms / 1000 + self._slack
    slot = await self._claim(game_id, level_tag, "inflight")
    t0 = self._now()
    try:
        parsed = await self._run_move(slot, game_id, target, params, allowed_zone, timeout)
    finally:
        await self._unclaim(slot, "inflight")
    ms = int((self._now() - t0) * 1000)
    if parsed.move is None or parsed.move in set(target):
        await self._reset_synced(slot)  # битый ход движка → следующий запрос cold (§4.6/A7)
        _log.warning("engine_invalid_move game=%s pid=%s move=%s", game_id, slot.pid, parsed.move)
        raise EngineError(...)
    _log.info("compute_move game=%s pid=%s moves=%d -> %s ms=%d", game_id, slot.pid, len(target), parsed.move, ms)
    return parsed.move
```

`_run_move` (под `io_lock`, retry-once+respawn) внутри `_attempt_move` строит дельту от `slot.synced`:

```python
async def _attempt_move(self, slot, game_id, target, params, allowed_zone, timeout_s):
    if slot.proc is None or not slot.proc.alive:
        await self._respawn(slot, game_id, reason="dead")   # выставит synced=None
    plan = plan_sync(slot.synced, target)
    if plan.cold:
        cmds = _move_commands(target, params, allowed_zone)        # START+INFO+BOARD
    else:
        cmds = incremental_move_commands(plan, target=target, params=params, allowed_zone=allowed_zone)
    proc = slot.proc
    async with asyncio.timeout(timeout_s):
        await proc.send(cmds)
        parsed = await self._read(proc, LineKind.MOVE)
    slot.synced = [*target, parsed.move]   # движок применил свой ход сам (§4.1)
    return parsed
```

`_run_move`/`_run_forbid` дублируют ту же retry-once+respawn обвязку, что текущий `_run` (на respawn synced сбрасывается → повтор строится как cold). `_read` — вынесенный цикл дренажа (пропускает `OK` от START/TAKEBACK, ловит `want`, на `ERROR` → `ProtocolError`). `_reset_synced(slot)` — под `io_lock`: `slot.synced = None`.

- [ ] **Step 4: Прогнать — зелено**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rapfi/registry.py backend/tests/unit/test_registry.py
git commit -m "feat(rj-t95): registry — инкрементальный sync позиции (synced + TURN/TAKEBACK)"
```

---

## Task 4: forbidden_points — warm YXSHOWFORBID / cold YXBOARD

**Files:**
- Modify: `backend/app/rapfi/registry.py`
- Test: `backend/tests/unit/test_registry.py`

- [ ] **Step 1: Failing-тест**

```python
@pytest.mark.asyncio
async def test_forbid_warm_only_yxshowforbid():
    procs = []
    async def spawn(**kw):
        p = FakeProc(["8,8", "FORBID ."]); procs.append(p); return p
    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)            # synced=[(7,7),(8,8)] (len2 → чёрный к ходу)
    procs[0].sent.clear()
    await reg.forbidden_points("g", [(7, 7), (8, 8)])   # == synced → тёплый
    sent = [c for batch in procs[0].sent for c in batch]
    assert sent == ["YXSHOWFORBID"]                     # ни START, ни YXBOARD, ни INFO
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]   # не тронут (read-only)
    await reg.close()


@pytest.mark.asyncio
async def test_forbid_cold_when_synced_none():
    procs = []
    async def spawn(**kw):
        p = FakeProc(["FORBID ."]); procs.append(p); return p
    reg = make_registry(spawn)
    await reg.forbidden_points("g", [(7, 7), (8, 8)])   # synced=None → cold YXBOARD без think
    sent = [c for batch in procs[0].sent for c in batch]
    assert "YXBOARD" in sent and "YXSHOWFORBID" in sent
    assert "START 15" not in sent and not any(s.startswith("INFO strength") for s in sent)
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]   # cold-форбид без INFO (§4.4/A8)
    await reg.close()
```

- [ ] **Step 2: Прогнать — упадёт.** Run: `... pytest tests/unit/test_registry.py -k forbid -v`

- [ ] **Step 3: Реализация `forbidden_points`/`_attempt_forbid`**

```python
async def forbidden_points(self, game_id, moves, *, level_tag="-"):
    if len(moves) % 2 != 0:
        return []
    target = [tuple(m) for m in moves]
    slot = await self._claim(game_id, level_tag, "inflight")
    try:
        parsed = await self._run_forbid(slot, game_id, target, _FORBID_TIMEOUT_S)
    finally:
        await self._unclaim(slot, "inflight")
    if parsed.forbidden is None:
        raise EngineError("engine returned no forbidden list")
    return list(parsed.forbidden)

async def _attempt_forbid(self, slot, game_id, target, timeout_s):
    if slot.proc is None or not slot.proc.alive:
        await self._respawn(slot, game_id, reason="dead")
    if slot.synced == target:                       # тёплый: только YXSHOWFORBID
        cmds = ["YXSHOWFORBID"]
    else:                                            # cold (вкл. synced=None): YXBOARD без think
        cmds = forbid_commands(target)              # YXBOARD…DONE YXSHOWFORBID, без INFO
        # synced выставим после успешного чтения
    proc = slot.proc
    async with asyncio.timeout(timeout_s):
        await proc.send(cmds)
        parsed = await self._read(proc, LineKind.FORBID)
    if slot.synced != target:
        slot.synced = target                        # YXBOARD заменил доску на target (своего хода нет)
    return parsed
```

- [ ] **Step 4: Прогнать — зелено.** Run: `... pytest tests/unit/test_registry.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/rapfi/registry.py backend/tests/unit/test_registry.py
git commit -m "feat(rj-t95): forbidden_points — warm YXSHOWFORBID, cold YXBOARD без newGame"
```

---

## Task 5: service.py — не запрашивать фолы для стороны-движка

**Files:**
- Modify: `backend/app/game/service.py`
- Test: `backend/tests/unit/test_game_service.py` / `test_game_service_contour.py`

- [ ] **Step 1: Failing-тест** (движок-чёрный: `advance` не зовёт `fouls`/`forbidden_points`)

В `test_game_service_contour.py` (паттерн файла: `_svc()` + counting-обёртка на `svc._adapter`,
явный `Game`; без `@pytest.mark.asyncio` — в этом файле asyncio-auto):

```python
async def test_advance_engine_black_does_not_query_fouls():
    from app.models.game import Game
    svc = _svc()
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points
    async def counting(game_id, moves, *, level_tag="-"):
        svc._adapter.calls += 1
        return await orig(game_id, moves, level_tag=level_tag)
    svc._adapter.forbidden_points = counting
    g = Game(id="g", owner_id=1, moves=[[7, 7], [8, 8]], undo_count=0, forbidden_log={},
             controllers={"black": {"kind": "engine", "level_id": "master"},
                          "white": {"kind": "user", "user_id": 1}},
             status="opponent_thinking")
    await svc._repo.create(g)
    await svc.advance(g)            # движок-чёрный ходит 3-м; фолы для него НЕ запрашиваются
    assert svc._adapter.calls == 0
```

Также **удалить** существующий `test_advance_engine_black_forbidden_move_errors`
(`test_game_service_contour.py:129`) — он проверял снимаемое поведение (приложение
отвергает фол-ход движка-чёрного → событие error); после правки `forbidden=[]` этот
сейфти-нет убран (доверяем легальности Rapfi, спека §6).

- [ ] **Step 2: Прогнать — упадёт** (сейчас `service.py:126` зовёт fouls для чёрного-движка).

- [ ] **Step 3: Реализация** — в `advance` заменить `service.py:126`:

```python
                # фолы движок соблюдает сам (RULE 4) — для его хода не запрашиваем (rj-t95)
                fb = []
                game.moves = [list(p) for p in apply_move(moves, mv, forbidden=fb)]
```

(Ветка интерактивной стороны, `service.py:113`, не трогается — человеку-чёрному фолы по-прежнему считаются и публикуются.)

- [ ] **Step 4: Прогнать — зелено.** Run: `cd backend && uv run pytest tests/unit/test_game_service_contour.py tests/unit/test_game_service.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/game/service.py backend/tests/unit/test_game_service_contour.py
git commit -m "feat(rj-t95): не запрашивать фолы для стороны-движка (движок их соблюдает сам)"
```

---

## Task 6: Интеграционная регрессия (живой движок) — undo-путь + warm-форбид

**Files:**
- Modify: `backend/tests/integration/test_registry_live.py`

- [ ] **Step 1: Тесты** (на ОДНОМ game_id, тёплый слот; target — сконструированные позиции)

```python
async def test_engine_blocks_four_after_undo(rapfi_paths):
    """rj-t95: тёплый процесс, серия с откатом — движок всё равно закрывает четвёрку."""
    reg = _reg(rapfi_paths)
    forcing = [(7, 7), (8, 7), (8, 6), (9, 7), (6, 8), (9, 5), (9, 8), (10, 7), (7, 8), (11, 7)]
    fast = EngineParams(strength=5, timeout_turn_ms=1500)
    try:
        await reg.compute_move("g", forcing[:6], fast)   # форвард
        await reg.compute_move("g", forcing[:4], fast)   # «откат» — короче → ветка TAKEBACK
        mv = await reg.compute_move("g", forcing, fast)  # форвард к форсирующей позиции
        assert mv == (12, 7)                              # обязан закрыть открытую четвёрку
    finally:
        await reg.close()


async def test_warm_forbid_no_reset(rapfi_paths):
    """Тёплый YXSHOWFORBID не сбрасывает слот: расчёт после форбида продолжает инкремент."""
    reg = _reg(rapfi_paths)
    fast = EngineParams(strength=5, timeout_turn_ms=1000)
    dbl3 = [(8, 7), (0, 0), (9, 7), (0, 2), (7, 8), (0, 4), (7, 9), (0, 6)]  # двойная тройка чёрных в (7,7)
    try:
        await reg.compute_move("g", dbl3, fast)              # synced прогрет
        synced_before = list(reg._slots["g"].synced)
        fb = await reg.forbidden_points("g", reg._slots["g"].synced)  # тёплый форбид
        assert reg._slots["g"].synced == synced_before       # слот не сброшен
    finally:
        await reg.close()
```

- [ ] **Step 2: Прогнать.** Run: `cd backend && uv run pytest tests/integration/test_registry_live.py -v`
Expected: PASS (если бинарь собран; без бинаря — skip по `rapfi_paths`).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_registry_live.py
git commit -m "test(rj-t95): регрессия — закрытие четвёрки после undo + warm-форбид без сброса"
```

---

## Task 7: Уборка мёртвого кода этапа-1

**Files:**
- Delete: `backend/scripts/play_cli.py`, `backend/tests/unit/test_play_cli.py`, `backend/tests/integration/test_adapter.py`
- Modify: `backend/app/rapfi/adapter.py` (удалить класс `RapfiAdapter`), `CLAUDE.md (корень репо)`, `backend/tests/integration/test_games_live.py:2`
- Перенести: engine-контракт-тесты из `test_adapter.py` в `test_registry_live.py`
- Сохранить: `backend/tests/integration/fixtures/hang_engine.sh`

- [ ] **Step 1: Перенести валидные engine-контракт-тесты** в `test_registry_live.py` (на `EngineRegistry`, game_id="g"): фолы double-three, 3×3/5×5-зоны, block-no-leak, wall-clock kill (через `hang_engine.sh`; ассерт `a._proc` → `reg._slots["g"].proc`/жив ли процесс), recovery после краха, real-levels-e2e. Тест «изоляция состояния между запросами» **НЕ переносить** (он утверждал снимаемый антипаттерн).

- [ ] **Step 2: Прогнать перенесённые — зелено.** Run: `cd backend && uv run pytest tests/integration/test_registry_live.py -v`

- [ ] **Step 3: Удалить файлы и класс**

```bash
git rm backend/scripts/play_cli.py backend/tests/unit/test_play_cli.py backend/tests/integration/test_adapter.py
```

В `adapter.py` удалить класс `RapfiAdapter` целиком (оставить `EngineError`, константы `_WALL_CLOCK_SLACK_S`/`_FORBID_TIMEOUT_S`/`_FORBID_PARAMS`, `_move_commands`, `incremental_move_commands`, `_zone_block`). Поправить импорты `process.py` если осиротели.

- [ ] **Step 4: Поправить ссылки**

- `CLAUDE.md (корень репо)` §Команды — удалить строку `uv run python -m scripts.play_cli …`.
- `backend/tests/integration/test_games_live.py:2` — комментарий `RapfiAdapter` → `EngineRegistry`.

- [ ] **Step 5: Полный прогон + линт**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest -q && uv run ruff check app tests scripts`
Expected: всё зелёное; нет осиротевших импортов `RapfiAdapter`/`play_cli`.

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "chore(rj-t95): убрать мёртвый этап-1 код — RapfiAdapter и play_cli"
```

---

## Ручное тестирование (Alexey, после Task 1–7)

Пересобрать/перезапустить сервер, сыграть партию **белыми** (движок чёрный) с **несколькими undo** в вебе — движок больше не зевает (закрывает угрозы, не лепит в угол). Лог `renju.engine`: на ходы после первого — `TURN`/`TAKEBACK`, `START` только на спауне/респауне.

## Самопроверка плана

- **Покрытие спеки:** §3.1 per-move INFO (T1 `tunable_commands`, T3 cold/warm); §4.1 synced+ход движка (T3); §4.2 sync-алгоритм (T1 `plan_sync`, T3); §4.3 YXBLOCK (T2 `incremental_move_commands`); §4.4 фолы warm/cold (T4) + drop engine-side (T5); §4.5 respawn→cold (T3 synced=None); §4.6 контракт `_run`+reset synced (T3); §6 регресс undo+warm-forbid (T6); §7.1 уборка (T7).
- **Типы согласованы:** `SyncPlan(cold, takebacks, turn)` — T1↔T2↔T3; `slot.synced: list[Point]|None` — T3↔T4↔T6.
- **Минорные план-замечания ревью учтены:** `hang_engine.sh` сохранён (T7 Step1/3), ассерт `_proc`→`slot.proc` (T7 Step1), комментарий `test_games_live.py:2` (T7 Step4).
- **FakeProc-механика** — как в существующем `test_registry.py`: `FakeProc(script)` (`script` = ответы `read_line`), `proc.sent` = список батчей посланных строк, паттерн `make_registry(spawn)`. Новых хелперов НЕ вводим (тесты Task 3/4 сплющивают `proc.sent` напрямую).
