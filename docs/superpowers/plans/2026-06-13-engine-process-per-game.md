# Процесс Rapfi на игру — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить единый процесс Rapfi на модель «процесс на игру» — реестр процессов по `game_id` с присутствием (enter/leave), idle-гашением, изоляцией и логированием по `game_id+pid`.

**Architecture:** `EngineRegistry` (app.rapfi) — изолированная подсистема, владеет `dict[game_id → EngineSlot]`; **один процесс на game_id** (check-before-spawn). Слот: `inflight` (refcount идущих расчётов — защита от kill во время хода), `presence` (счётчик устройств — гейтит триггер ВЫХОД), `io_lock`, `last_activity`. Счётчики инкрементятся **в той же секции `registry_lock`**, что и выбор/создание слота (TOCTOU невозможен). Два триггера гашения: `leave` довёл presence→0 при свободном процессе; idle-sweep по неактивности (`inflight==0 && idle>timeout`, без гейта presence). Без лимита. Spawn инъектируется (фейк для unit-тестов). `game_id` протягивается через `Player`/`GameService`; enter/leave — тонкие эндпоинты router → реестр.

**Tech Stack:** Python 3.13, asyncio (`Condition`/`Event`/`Lock`), pydantic-settings, pytest/pytest-asyncio. Спека: `docs/superpowers/specs/2026-06-13-engine-process-per-game-design.md`.

**Тесты (последовательно):** `cd backend && uv run pytest -q`. Один: `uv run pytest tests/unit/test_registry.py::test_name -v`.

---

## File Structure

- **Create** `backend/app/rapfi/registry.py` — `EngineSlot` + `EngineRegistry`.
- **Modify** `backend/app/rapfi/process.py` — свойство `pid`.
- **Keep** `backend/app/rapfi/adapter.py` — helpers `_move_commands`/`EngineError`/`_FORBID_PARAMS`/`_WALL_CLOCK_SLACK_S`/`_FORBID_TIMEOUT_S` (реестр импортирует). Класс `RapfiAdapter` остаётся со старой сигнатурой — только для `tests/integration/test_adapter.py`.
- **Modify** `backend/app/config.py` — `engine_idle_timeout_s`, `engine_sweep_interval_s` (существующий `engine_kill_grace_s` переиспользуется; лимита НЕТ).
- **Modify** `backend/app/game/players.py`, `backend/app/game_service.py`, `backend/app/game/service.py`, `backend/scripts/play_cli.py` — протянуть `game_id`/`level_tag`.
- **Modify** `backend/app/routers/games.py` — эндпоинты `POST /api/games/{id}/enter` и `/leave`.
- **Modify** `backend/app/app_factory.py` — реестр вместо адаптера; sweep-таск; shutdown.
- **Create** `backend/tests/unit/test_registry.py`; **Create** `backend/tests/integration/test_registry_live.py`.
- **Modify** `backend/tests/conftest.py`, `tests/unit/test_players.py`, `tests/unit/test_game_service.py`, `tests/unit/test_game_service_contour.py` — новые сигнатуры/фейки.
- **Follow-up (фронт, отдельно):** игровой экран зовёт `enter` на mount и `leave` на выходе на главный (rj-h0y) — §«Frontend» ниже.

---

## Task 1: `RapfiProcess.pid`

**Files:** Modify `backend/app/rapfi/process.py`; Test `backend/tests/integration/test_process.py`

- [ ] **Step 1: Failing test** (в `test_process.py`)

```python
async def test_pid_exposed_after_spawn(rapfi_paths):
    bin_path, config_path, cwd = rapfi_paths
    proc = await RapfiProcess.spawn(bin_path=bin_path, config_path=config_path, cwd=cwd)
    try:
        assert isinstance(proc.pid, int) and proc.pid > 0
    finally:
        await proc.terminate(grace_s=2.0)
```

- [ ] **Step 2: Run** — `cd backend && uv run pytest tests/integration/test_process.py::test_pid_exposed_after_spawn -v` — FAIL (`AttributeError`) или SKIP без бинаря.
- [ ] **Step 3: Implement** — в `process.py` рядом с `alive`:

```python
    @property
    def pid(self) -> int:
        return self._proc.pid
```

- [ ] **Step 4: Run** — PASS/SKIP. **Step 5: Commit** — `git add backend/app/rapfi/process.py backend/tests/integration/test_process.py && git commit -m "feat(rj-899): RapfiProcess.pid для логирования"`

---

## Task 2: Settings — idle/sweep

**Files:** Modify `backend/app/config.py` (после `busy_timeout_ms`); Test `backend/tests/unit/test_config.py`

- [ ] **Step 1: Failing test**

```python
def test_engine_registry_defaults():
    from app.config import Settings
    s = Settings()
    assert s.engine_idle_timeout_s > 0 and s.engine_sweep_interval_s > 0
```

- [ ] **Step 2: Run** — FAIL (`AttributeError`).
- [ ] **Step 3: Implement** — после `busy_timeout_ms: int = 5000`:

```python
    # Движковые процессы (rj-899): предварительные, калибруются. kill_grace_s — выше.
    engine_idle_timeout_s: float = 180.0  # гасим процесс партии по неактивности
    engine_sweep_interval_s: float = 30.0  # период idle-sweep
```

- [ ] **Step 4: Run** — PASS. **Step 5: Commit** — `git add backend/app/config.py backend/tests/unit/test_config.py && git commit -m "feat(rj-899): настройки idle/sweep реестра"`

---

## Task 3: `EngineRegistry` — слот, claim (get-or-create+counter+spawn), расчёт

Refcount-claim под `registry_lock` закрывает TOCTOU; spawn инъектируется.

**Files:** Create `backend/app/rapfi/registry.py`; Test `backend/tests/unit/test_registry.py`

- [ ] **Step 1: Failing test — фейк-процесс + базовый compute_move**

```python
import asyncio
import pytest
from app.domain.engine_params import EngineParams
from app.rapfi.registry import EngineRegistry

P = EngineParams(strength=50, timeout_turn_ms=200)


class FakeProc:
    _seq = 1000
    def __init__(self, script):
        self._script = list(script); self.sent = []; self._alive = True
        FakeProc._seq += 1; self.pid = FakeProc._seq
    @property
    def alive(self): return self._alive
    async def send(self, lines): self.sent.append(lines)
    async def read_line(self):
        if not self._script: await asyncio.sleep(3600)  # hang
        return self._script.pop(0)
    async def terminate(self, *, grace_s): self._alive = False


def make_registry(spawn, **kw):
    d = dict(bin_path="/x", config_path="/y", cwd="/z", idle_timeout_s=100.0, kill_grace_s=0.01)
    d.update(kw)
    return EngineRegistry(spawn=spawn, **d)


@pytest.mark.asyncio
async def test_compute_move_spawns_and_returns():
    spawned = []
    async def spawn(**kw):
        p = FakeProc(["MESSAGE loading", "7,8"]); spawned.append(p); return p
    reg = make_registry(spawn)
    assert await reg.compute_move("g1", [(7, 7)], P) == (7, 8)
    assert len(spawned) == 1
    await reg.close()
```

- [ ] **Step 2: Run** — FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement — `registry.py`**

```python
"""Реестр процессов Rapfi по game_id (rj-899). Один процесс на партию, изоляция.

Защита от kill во время расчёта/при наличии зрителей — refcount'ы под одним
registry_lock: `inflight` (идущие расчёты), `presence` (устройства). Оба инкрементятся
в той же секции, что и выбор/создание слота → TOCTOU невозможен.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.engine_params import EngineParams
from ..domain.values import Point
from .adapter import _FORBID_PARAMS, _FORBID_TIMEOUT_S, _WALL_CLOCK_SLACK_S, EngineError, _move_commands
from .process import EngineProcessDied, RapfiProcess
from .protocol import LineKind, ParsedLine, ProtocolError, forbid_commands, init_commands, parse_line

_log = logging.getLogger("renju.engine")
SpawnFn = Callable[..., Awaitable[object]]


@dataclass
class EngineSlot:
    proc: object | None = None
    pid: int | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    io_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    inflight: int = 0
    presence: int = 0
    last_activity: float = 0.0
    level_tag: str = "-"


class EngineRegistry:
    def __init__(self, *, bin_path: Path, config_path: Path, cwd: Path,
                 idle_timeout_s: float, kill_grace_s: float = 2.0,
                 wall_clock_slack_s: float = _WALL_CLOCK_SLACK_S,
                 spawn: SpawnFn = RapfiProcess.spawn, now: Callable[[], float] = time.monotonic):
        self._bin, self._config, self._cwd = bin_path, config_path, cwd
        self._idle, self._grace, self._slack = idle_timeout_s, kill_grace_s, wall_clock_slack_s
        self._spawn, self._now = spawn, now
        self._slots: dict[str, EngineSlot] = {}
        self._cond = asyncio.Condition()  # его lock = registry_lock
        self._closing = False

    async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
        commands = _move_commands(moves, params, allowed_zone)
        timeout = params.timeout_turn_ms / 1000 + self._slack
        slot = await self._claim(game_id, level_tag, "inflight")
        t0 = self._now()  # после claim: ms = время расчёта, не spawn (spawn — своя лог-строка)
        try:
            parsed = await self._run(slot, game_id, commands, LineKind.MOVE, timeout)
        finally:
            await self._unclaim(slot, "inflight")
        ms = int((self._now() - t0) * 1000)
        if parsed.move is None:
            _log.warning("engine_invalid_move game=%s pid=%s reason=no-move", game_id, slot.pid)
            raise EngineError("engine returned no move")
        if parsed.move in set(moves):
            _log.warning("engine_invalid_move game=%s pid=%s move=%s reason=occupied", game_id, slot.pid, parsed.move)
            raise EngineError(f"engine returned occupied cell: {parsed.move}")
        _log.info("compute_move game=%s pid=%s moves=%d -> %s ms=%d", game_id, slot.pid, len(moves), parsed.move, ms)
        return parsed.move

    async def forbidden_points(self, game_id, moves, *, level_tag="-"):
        if len(moves) % 2 != 0:
            return []
        commands = init_commands(_FORBID_PARAMS) + forbid_commands(moves)
        slot = await self._claim(game_id, level_tag, "inflight")
        try:
            parsed = await self._run(slot, game_id, commands, LineKind.FORBID, _FORBID_TIMEOUT_S)
        finally:
            await self._unclaim(slot, "inflight")
        if parsed.forbidden is None:
            raise EngineError("engine returned no forbidden list")
        _log.debug("forbidden_points game=%s pid=%s moves=%d n=%d", game_id, slot.pid, len(moves), len(parsed.forbidden))
        return list(parsed.forbidden)

    async def close(self):
        async with self._cond:
            self._closing = True
            items = list(self._slots.items())
            self._slots.clear()
            self._cond.notify_all()
        await asyncio.gather(*[self._terminate(s, gid, "shutdown") for gid, s in items if s.proc], return_exceptions=True)

    # --- claim/unclaim: get-or-create + counter под одним локом, затем spawn вне лока ---

    async def _claim(self, game_id, level_tag, counter):  # counter: "inflight" | "presence"
        while True:  # петля, не рекурсия: при провале создателя waiter пересоздаёт без роста стека
            async with self._cond:
                if self._closing:
                    raise EngineError("registry closing")
                slot = self._slots.get(game_id)
                creator = slot is None
                if creator:
                    slot = EngineSlot(level_tag=level_tag, last_activity=self._now())
                    self._slots[game_id] = slot
                setattr(slot, counter, getattr(slot, counter) + 1)
                slot.last_activity = self._now()
            if creator:
                await self._spawn_into(game_id, slot, counter)
                return slot
            await slot.ready.wait()
            if slot.proc is not None:
                return slot
            await self._unclaim(slot, counter)  # создатель упал → снять заявку и ретрай (loop)

    async def _spawn_into(self, game_id, slot, counter):
        try:
            proc = await self._spawn(bin_path=self._bin, config_path=self._config, cwd=self._cwd)
        except BaseException:
            async with self._cond:
                setattr(slot, counter, getattr(slot, counter) - 1)
                self._slots.pop(game_id, None)
                slot.ready.set()
                self._cond.notify_all()
            raise
        orphan = None
        async with self._cond:
            if self._closing or self._slots.get(game_id) is not slot:
                orphan = proc
                setattr(slot, counter, getattr(slot, counter) - 1)
                slot.ready.set()
                self._cond.notify_all()
            else:
                slot.proc, slot.pid = proc, proc.pid
                slot.ready.set()
                _log.info("spawn game=%s pid=%s level_tag=%s", game_id, proc.pid, slot.level_tag)
        if orphan is not None:
            await orphan.terminate(grace_s=self._grace)
            raise EngineError("registry closing during spawn")

    async def _unclaim(self, slot, counter):
        async with self._cond:
            setattr(slot, counter, getattr(slot, counter) - 1)
            slot.last_activity = self._now()
            self._cond.notify_all()

    # --- расчёт на слоте (retry-once + respawn per-slot) ---

    async def _run(self, slot, game_id, commands, want, timeout_s):
        async with slot.io_lock:
            try:
                return await self._attempt(slot, game_id, commands, want, timeout_s)
            except (TimeoutError, EngineProcessDied, ProtocolError):
                await self._respawn(slot, game_id, reason="hang")
            try:
                return await self._attempt(slot, game_id, commands, want, timeout_s)
            except (TimeoutError, EngineProcessDied, ProtocolError) as e:
                await self._respawn(slot, game_id, reason="hang")
                raise EngineError(f"engine failed twice: {e!r}") from e

    async def _attempt(self, slot, game_id, commands, want, timeout_s):
        if slot.proc is None or not slot.proc.alive:
            await self._respawn(slot, game_id, reason="dead")
        async with asyncio.timeout(timeout_s):
            await slot.proc.send(commands)
            while True:
                parsed = parse_line(await slot.proc.read_line())
                if parsed.kind is want:
                    return parsed
                if parsed.kind is LineKind.ERROR:
                    raise ProtocolError(parsed.text)

    async def _respawn(self, slot, game_id, *, reason):
        if slot.proc is not None:  # лог смены pid (наблюдаемость respawn, §3.1/§7)
            _log.warning("kill game=%s pid=%s reason=%s", game_id, slot.pid, reason)
            await slot.proc.terminate(grace_s=self._grace)
        slot.proc = await self._spawn(bin_path=self._bin, config_path=self._config, cwd=self._cwd)
        slot.pid = slot.proc.pid
        _log.info("spawn game=%s pid=%s level_tag=%s reason=respawn", game_id, slot.pid, slot.level_tag)

    async def _terminate(self, slot, game_id, reason):
        if slot.proc is not None:
            pid = slot.pid
            await slot.proc.terminate(grace_s=self._grace)
            slot.proc = None
            _log.info("kill game=%s pid=%s reason=%s", game_id, pid, reason)
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_registry.py::test_compute_move_spawns_and_returns -v` — PASS.
- [ ] **Step 5: Failing test — дедуп + провал spawn**

```python
@pytest.mark.asyncio
async def test_concurrent_compute_one_process():
    spawned = []
    async def spawn(**kw):
        await asyncio.sleep(0.02); p = FakeProc(["7,8", "7,9"]); spawned.append(p); return p
    reg = make_registry(spawn)
    r = await asyncio.gather(reg.compute_move("g", [(7, 7)], P), reg.compute_move("g", [(7, 7)], P))
    assert len(spawned) == 1 and set(r) <= {(7, 8), (7, 9)}
    await reg.close()


@pytest.mark.asyncio
async def test_spawn_failure_clears_placeholder():
    n = {"i": 0}
    async def spawn(**kw):
        n["i"] += 1
        if n["i"] == 1: raise OSError("boom")
        return FakeProc(["7,8"])
    reg = make_registry(spawn)
    with pytest.raises(OSError):
        await reg.compute_move("g", [(7, 7)], P)
    assert await asyncio.wait_for(reg.compute_move("g", [(7, 7)], P), 2) == (7, 8)
    await reg.close()
```

- [ ] **Step 6: Run** — PASS.
- [ ] **Step 7: Commit** — `git add backend/app/rapfi/registry.py backend/tests/unit/test_registry.py && git commit -m "feat(rj-899): EngineRegistry — claim/spawn/расчёт, дедуп, retry-once per-slot"`

---

## Task 4: Присутствие — mark_present/mark_absent (enter/leave) + release

**Files:** Modify `backend/app/rapfi/registry.py`; Test `backend/tests/unit/test_registry.py`

- [ ] **Step 1: Failing test — enter спаунит, 2-е устройство переиспользует, последний leave гасит, не-последний — нет, leave при расчёте не рвёт**

```python
@pytest.mark.asyncio
async def test_enter_spawns_second_device_reuses():
    spawned = []
    async def spawn(**kw):
        p = FakeProc([]); spawned.append(p); return p
    reg = make_registry(spawn)
    await reg.mark_present("g")            # устройство 1 → spawn
    await reg.mark_present("g")            # устройство 2 → переиспользует
    assert len(spawned) == 1 and reg._slots["g"].presence == 2
    await reg.close()


@pytest.mark.asyncio
async def test_last_leave_kills_not_last_keeps():
    procs = []
    async def spawn(**kw):
        p = FakeProc([]); procs.append(p); return p
    reg = make_registry(spawn)
    await reg.mark_present("g"); await reg.mark_present("g")
    await reg.mark_absent("g")             # presence 2→1: не трогаем
    assert "g" in reg._slots and procs[0].alive
    await reg.mark_absent("g")             # presence 1→0: гасим
    assert "g" not in reg._slots and procs[0].alive is False
    await reg.close()


@pytest.mark.asyncio
async def test_leave_does_not_kill_during_compute():
    async def spawn(**kw): return FakeProc([])  # зависнет → inflight держится
    reg = make_registry(spawn)
    await reg.mark_present("g")
    task = asyncio.create_task(reg.compute_move("g", [(7, 7)], EngineParams(strength=1, timeout_turn_ms=5000)))
    await asyncio.sleep(0.05)              # inflight=1
    await reg.mark_absent("g")             # presence 1→0, но inflight>0 → НЕ гасим
    assert "g" in reg._slots
    task.cancel(); await reg.close()


@pytest.mark.asyncio
async def test_release_kills_idle():  # API под удаление партии (rj-as6); inflight>0-ветка — как в mark_absent
    procs = []
    async def spawn(**kw):
        p = FakeProc([]); procs.append(p); return p
    reg = make_registry(spawn)
    await reg.mark_present("g")
    await reg.release("g")                 # inflight==0 → гасим
    assert "g" not in reg._slots and procs[0].alive is False
    await reg.close()
```

- [ ] **Step 2: Run** — FAIL (`AttributeError: ... mark_present`).
- [ ] **Step 3: Implement** — добавить в `EngineRegistry`:

```python
    async def mark_present(self, game_id, level_tag="-"):
        await self._claim(game_id, level_tag, "presence")  # presence++ + spawn если первый

    async def mark_absent(self, game_id, *, reason="leave"):
        victim = None
        async with self._cond:
            slot = self._slots.get(game_id)
            if slot is None or slot.presence == 0:
                return
            slot.presence -= 1
            slot.last_activity = self._now()
            if slot.presence == 0 and slot.inflight == 0:  # последний ушёл и не считаем
                self._slots.pop(game_id, None)
                victim = slot
                self._cond.notify_all()
        if victim is not None:
            await self._terminate(victim, game_id, reason)

    async def release(self, game_id, *, reason="delete"):  # под удаление партии (rj-as6)
        victim = None
        async with self._cond:
            slot = self._slots.get(game_id)
            if slot is None or slot.inflight > 0:
                return
            self._slots.pop(game_id, None)
            victim = slot
            self._cond.notify_all()
        if victim is not None:
            await self._terminate(victim, game_id, reason)
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_registry.py -k "enter or leave or device" -v` — PASS.
- [ ] **Step 5: Commit** — `git add backend/app/rapfi/registry.py backend/tests/unit/test_registry.py && git commit -m "feat(rj-899): presence — mark_present/mark_absent (enter/leave), release"`

---

## Task 5: idle-sweep (без гейта presence) + close

**Files:** Modify `backend/app/rapfi/registry.py`; Test `backend/tests/unit/test_registry.py`

- [ ] **Step 1: Failing test — sweep реапит по простою; не трогает inflight; реапит зависший presence (дрейф)**

```python
@pytest.mark.asyncio
async def test_sweep_reaps_idle_regardless_of_presence():
    clock = {"t": 0.0}
    async def spawn(**kw): return FakeProc([])
    reg = make_registry(spawn, idle_timeout_s=10.0, now=lambda: clock["t"])
    await reg.mark_present("g")            # presence=1 (зависший «дрейф»)
    clock["t"] = 5.0; await reg.sweep_once()
    assert "g" in reg._slots               # ещё активен
    clock["t"] = 20.0; await reg.sweep_once()
    assert "g" not in reg._slots           # по простою реапнут, ХОТЯ presence>0
    await reg.close()


@pytest.mark.asyncio
async def test_sweep_skips_inflight():
    clock = {"t": 0.0}
    async def spawn(**kw): return FakeProc([])  # зависнет → inflight
    reg = make_registry(spawn, idle_timeout_s=1.0, now=lambda: clock["t"])
    task = asyncio.create_task(reg.compute_move("g", [(7, 7)], EngineParams(strength=1, timeout_turn_ms=5000)))
    await asyncio.sleep(0.05)
    clock["t"] = 100.0; await reg.sweep_once()
    assert "g" in reg._slots               # inflight>0 → не реапим
    task.cancel(); await reg.close()
```

- [ ] **Step 2: Run** — FAIL (`AttributeError: ... sweep_once`).
- [ ] **Step 3: Implement** — добавить в `EngineRegistry`:

```python
    async def sweep_once(self):
        async with self._cond:
            victims = [(gid, s) for gid, s in self._slots.items()
                       if s.inflight == 0 and self._now() - s.last_activity > self._idle]
            for gid, _s in victims:
                self._slots.pop(gid, None)
            if victims:
                self._cond.notify_all()
        await asyncio.gather(*[self._terminate(s, gid, "idle") for gid, s in victims], return_exceptions=True)
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_registry.py -k "sweep" -v` — PASS.
- [ ] **Step 5: Commit** — `git add backend/app/rapfi/registry.py backend/tests/unit/test_registry.py && git commit -m "feat(rj-899): idle-sweep по неактивности (без гейта presence), пропуск inflight"`

---

## Task 6: Логирование — проверка контракта

**Files:** Modify (строки уже в Task 3–5); Test `backend/tests/unit/test_registry.py`

- [ ] **Step 1: Verify test — spawn/compute/kill с game+pid**

```python
@pytest.mark.asyncio
async def test_logs_carry_game_and_pid(caplog):
    import logging
    async def spawn(**kw): return FakeProc(["7,8"])
    reg = make_registry(spawn)
    with caplog.at_level(logging.INFO, logger="renju.engine"):
        await reg.mark_present("game-xyz")
        await reg.compute_move("game-xyz", [(7, 7)], P)
        await reg.mark_absent("game-xyz")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "game-xyz" in text and "pid=" in text
    assert "spawn" in text and "compute_move" in text and "kill" in text
    await reg.close()
```

- [ ] **Step 2: Run** — PASS (строки уже есть; иначе добавить недостающую). **Step 3: Commit** — `git add backend/tests/unit/test_registry.py && git commit -m "test(rj-899): лог-контракт renju.engine (game_id+pid)"`

---

## Task 7: Протягивание game_id + обновление каллеров/фейков

**Files:** Modify `players.py`, `game_service.py`, `game/service.py`, `scripts/play_cli.py`, тесты `test_players.py`, `test_game_service.py`, `test_game_service_contour.py`

- [ ] **Step 1: Failing test — EnginePlayer несёт game_id** (`test_players.py`)

```python
async def test_engine_player_passes_game_id():
    from app.domain.engine_params import EngineParams
    from app.game.controllers import Engine
    from app.game.players import make_player
    captured = {}
    class FakeReg:
        async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
            captured["game_id"] = game_id; captured["level_tag"] = level_tag; return (7, 8)
    levels = {"novice": EngineParams(strength=1, timeout_turn_ms=100)}
    p = make_player(Engine("novice"), FakeReg(), levels, "game-77")
    assert await p.take_turn([(7, 7)]) == (7, 8)
    assert captured["game_id"] == "game-77" and captured["level_tag"] == "novice"
```

Обновить `test_make_player_dispatch` — 4-й арг `"g"`: `make_player(User(7), fake, levels, "g")`, `make_player(Engine("master"), fake, levels, "g")`.

- [ ] **Step 2: Run** — FAIL (3 арг). 
- [ ] **Step 3: Implement** — `players.py`:

```python
class EnginePlayer:
    def __init__(self, adapter, params, game_id: str, level_tag: str = "-"):
        self._adapter = adapter; self._params = params
        self._game_id = game_id; self._level_tag = level_tag
    async def take_turn(self, moves: Sequence[Point]) -> Point | None:
        return await engine_move(self._adapter, moves, self._params, self._game_id, self._level_tag)


def make_player(ctl: Controller, adapter, levels: dict, game_id: str) -> Player:
    if isinstance(ctl, User):
        return InteractivePlayer(ctl.user_id)
    return EnginePlayer(adapter, levels[ctl.level_id], game_id, level_tag=ctl.level_id)
```

`game_service.py` — `engine_move` (game_id первым позиционным у adapter):

```python
async def engine_move(adapter, moves, params, game_id: str, level_tag: str = "-") -> Point:
    zone = opening_zone(len(moves))
    return await adapter.compute_move(game_id, moves, params, allowed_zone=zone, level_tag=level_tag)
```

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_players.py -v` — PASS.
- [ ] **Step 5: Failing test — `test_game_service.py` `_FakeAdapter` под новую сигнатуру**

```python
class _FakeAdapter:
    def __init__(self): self.received_zone = "unset"; self.received_game_id = None
    async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
        self.received_zone = allowed_zone; self.received_game_id = game_id; return (8, 8)

async def test_engine_move_passes_opening_zone_as_allowed_zone():
    fake = _FakeAdapter()
    move = await engine_move(fake, [(7, 7)], EngineParams(strength=50, timeout_turn_ms=1000), "g1")  # type: ignore[arg-type]
    assert move == (8, 8) and fake.received_zone == opening_zone(1) and fake.received_game_id == "g1"

async def test_engine_move_unrestricted_after_opening():
    fake = _FakeAdapter()
    await engine_move(fake, [(7, 7), (8, 8), (9, 9), (6, 6)], EngineParams(strength=50, timeout_turn_ms=1000), "g2")  # type: ignore[arg-type]
    assert fake.received_zone is None
```

- [ ] **Step 6: Run** — FAIL (старая сигнатура).
- [ ] **Step 7: Implement — `service.py`:**
  - `_players(self, game)`: `make_player(controller_from_json(c), self._adapter, self._levels, game.id)`.
  - `fouls(self, game, moves)`: `pts = await self._adapter.forbidden_points(game.id, moves, level_tag="-")`.
  - НЕ убивать процесс по завершению/в advance/submit_move (откат после финиша разрешён — `UndoPolicy.after_game_end`). `release()` здесь не вызывается.

- [ ] **Step 8: Implement — обновить фейки `test_game_service_contour.py`:**
  - `FakeAdapter` (11–15): `forbidden_points(self, game_id, moves, *, level_tag="-")`, `compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-")`.
  - `boom` (118): `async def boom(game_id, moves, params, allowed_zone=None, *, level_tag="-"):`.
  - `_SeqAdapter` (314–323): `forbidden_points(self, game_id, moves, *, level_tag="-")`, `compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-")` (`close` без изменений).
  - Обёртки `counting` для `forbidden_points` (32, 213, 282): `async def counting(game_id, moves):` + `await orig(game_id, moves)`. `counting(*a, **k)` (247) — без изменений.

- [ ] **Step 9: Implement — `scripts/play_cli.py`:** `RapfiAdapter` → `EngineRegistry`, `game_id="cli"`:

```python
    from app.rapfi.registry import EngineRegistry
    adapter = EngineRegistry(bin_path=settings.resolved_rapfi_bin(), config_path=settings.rapfi_config,
                             cwd=REPO_ROOT, idle_timeout_s=600.0, kill_grace_s=settings.engine_kill_grace_s)
    ...
    forbidden = await adapter.forbidden_points("cli", moves)               # было forbidden_points(moves)
    engine_pt = await engine_move(adapter, moves, params, "cli", level.id) # было engine_move(adapter, moves, params)
```

(import `RapfiAdapter` убрать.)

- [ ] **Step 10: Run** — `uv run pytest tests/unit/test_game_service.py tests/unit/test_game_service_contour.py tests/unit/test_players.py -v` — PASS.
- [ ] **Step 11: Commit** — `git add backend/app/game/players.py backend/app/game_service.py backend/app/game/service.py backend/scripts/play_cli.py backend/tests/unit/test_players.py backend/tests/unit/test_game_service.py backend/tests/unit/test_game_service_contour.py && git commit -m "feat(rj-899): протянуть game_id (players/service/play_cli) + обновить фейки"`

---

## Task 8: enter/leave-эндпоинты + lifespan + conftest fake

**Files:** Modify `backend/app/routers/games.py`, `backend/app/app_factory.py`, `backend/tests/conftest.py`; Test `backend/tests/api/test_games_endpoints.py`

- [ ] **Step 1: Failing test — enter/leave дёргают реестр** (в `test_games_endpoints.py`, через `games_api`-фикстуру)

```python
async def test_enter_leave_call_registry(app, client, games_api):
    calls = []
    class PresenceAdapter(games_api.FakeAdapter):
        async def mark_present(self, game_id, level_tag="-"): calls.append(("enter", game_id))
        async def mark_absent(self, game_id, *, reason="leave"): calls.append(("leave", game_id))
    app.state.adapter = PresenceAdapter()
    await games_api.seed_login(app, client)
    g = (await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})).json()
    gid = g["id"]
    assert (await client.post(f"/api/games/{gid}/enter")).status_code == 200
    assert (await client.post(f"/api/games/{gid}/leave")).status_code == 200
    assert ("enter", gid) in calls and ("leave", gid) in calls
```

- [ ] **Step 2: Run** — FAIL (404: эндпоинтов нет).
- [ ] **Step 3: Implement — `games.py`** (после `undo`-эндпоинта). Хелпер level_tag + два эндпоинта:

```python
def _engine_level_tag(controllers: dict) -> str:
    for c in controllers.values():
        if c.get("kind") == "engine":
            return c["level_id"]
    return "-"


@router.post("/games/{game_id}/enter")
async def enter(game_id: str, request: Request,
                user: Annotated[CurrentUser, Depends(current_user)],
                session: Annotated[AsyncSession, Depends(get_session)]):
    game = await _service(request, session).get_game(game_id, user.user_id)  # 404 если нет доступа
    adapter = request.app.state.adapter
    if adapter is not None:
        await adapter.mark_present(game_id, _engine_level_tag(game.controllers))
    return {"ok": True}


@router.post("/games/{game_id}/leave")
async def leave(game_id: str, request: Request,
                user: Annotated[CurrentUser, Depends(current_user)],
                session: Annotated[AsyncSession, Depends(get_session)]):
    await _service(request, session).get_game(game_id, user.user_id)  # 404 если нет доступа
    adapter = request.app.state.adapter
    if adapter is not None:
        await adapter.mark_absent(game_id)
    return {"ok": True}
```

- [ ] **Step 4: Implement — conftest `_FakeAdapter`** (добавить presence-методы):

```python
class _FakeAdapter:
    async def forbidden_points(self, game_id, moves, *, level_tag="-"):
        return []
    async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
        occupied = {tuple(m) for m in moves}
        cells = sorted(allowed_zone) if allowed_zone else [(x, y) for x in range(15) for y in range(15)]
        for c in cells:
            if tuple(c) not in occupied:
                return tuple(c)
        raise AssertionError("board full")
    async def mark_present(self, game_id, level_tag="-"): pass
    async def mark_absent(self, game_id, *, reason="leave"): pass
    async def close(self): pass
```

- [ ] **Step 5: Run** — `uv run pytest tests/api/test_games_endpoints.py -v`. Новый `test_enter_leave_call_registry` зеленеет уже после Step 3 (эндпоинты) + Step 4 (фейк) — lifespan-wire (Step 6) для НЕГО не нужен. Существующие create/move/undo-тесты с `_FakeAdapter` — PASS. Step 6 нужен для реального реестра в проде/полном прогоне.
- [ ] **Step 6: Implement — `app_factory.py` lifespan** (реестр вместо адаптера + sweep + shutdown):

```python
        from .rapfi.registry import EngineRegistry
        try:
            app.state.adapter = EngineRegistry(
                bin_path=settings.resolved_rapfi_bin(), config_path=settings.rapfi_config, cwd=REPO_ROOT,
                idle_timeout_s=settings.engine_idle_timeout_s, kill_grace_s=settings.engine_kill_grace_s,
            )
        except FileNotFoundError:
            logging.getLogger("renju").warning("Rapfi bin не собран — adapter=None")
            app.state.adapter = None

        async def _sweep_loop():
            while True:
                await asyncio.sleep(settings.engine_sweep_interval_s)
                try:
                    await app.state.adapter.sweep_once()
                except Exception:
                    logging.getLogger("renju.engine").exception("sweep failed")
        app.state.engine_sweep = asyncio.create_task(_sweep_loop()) if app.state.adapter is not None else None
```

В shutdown (после `await asyncio.gather(*bg, ...)`, перед `adapter.close()`):

```python
        if getattr(app.state, "engine_sweep", None) is not None:
            app.state.engine_sweep.cancel()
            await asyncio.gather(app.state.engine_sweep, return_exceptions=True)
```

- [ ] **Step 7: Run** — `uv run pytest tests/api/ -v` — PASS.
- [ ] **Step 8: Полный прогон** — `cd backend && uv run pytest -q` — PASS (integration реестра/процесса — SKIP без бинаря).
- [ ] **Step 9: Lint** — `cd backend && uv run ruff check app tests scripts && uv run ruff format app tests scripts`.
- [ ] **Step 10: Commit** — `git add backend/app/routers/games.py backend/app/app_factory.py backend/tests/conftest.py backend/tests/api/test_games_endpoints.py && git commit -m "feat(rj-899): enter/leave-эндпоинты + EngineRegistry в lifespan + sweep-таск"`

---

## Task 9: Integration — реестр против живого движка

**Files:** Create `backend/tests/integration/test_registry_live.py`

- [ ] **Step 1: Тесты — разные партии = разные pid, общая партия = один; rj-t95-регрессия**

```python
import pytest
from app.domain.engine_params import EngineParams
from app.rapfi.registry import EngineRegistry

P = EngineParams(strength=5, timeout_turn_ms=1000)


def _reg(rapfi_paths):
    b, c, cwd = rapfi_paths
    return EngineRegistry(bin_path=b, config_path=c, cwd=cwd, idle_timeout_s=100.0)


@pytest.mark.asyncio
async def test_distinct_games_distinct_pids(rapfi_paths):
    reg = _reg(rapfi_paths)
    try:
        await reg.compute_move("game-a", [(7, 7)], P)
        await reg.compute_move("game-b", [(7, 7)], P)
        assert reg._slots["game-a"].pid != reg._slots["game-b"].pid     # разные партии — разные процессы
        await reg.compute_move("game-a", [(7, 7), (8, 8)], P)            # та же партия — тот же процесс
    finally:
        await reg.close()


@pytest.mark.asyncio
async def test_engine_blocks_winning_four(rapfi_paths):
    """rj-t95-регрессия: на СВЕЖЕМ процессе движок закрывает открытую четвёрку белых."""
    reg = _reg(rapfi_paths)
    moves = [(7, 7), (8, 7), (8, 6), (9, 7), (6, 8), (9, 5), (9, 8), (10, 7), (7, 8), (11, 7)]
    try:
        assert await reg.compute_move("g", moves, EngineParams(strength=5, timeout_turn_ms=1500)) == (12, 7)
    finally:
        await reg.close()
```

- [ ] **Step 2: Run** — `cd backend && uv run pytest tests/integration/test_registry_live.py -v` — PASS при собранном бинаре (иначе SKIP).
- [ ] **Step 3: Ручной smoke (Alexey)** — партия на двух устройствах: один pid в логах (`grep 'game='`); закрытие на одном не гасит процесс; выход с обоих → kill. **Ждать подтверждения.**
- [ ] **Step 4: Commit** — `git add backend/tests/integration/test_registry_live.py && git commit -m "test(rj-899): integration — pid по партиям + rj-t95-регрессия"`

---

## Frontend (отдельный шаг, после бэка)

Игровой экран (`/game/:id`) должен:
- на mount — `POST /api/games/{id}/enter` (presence++, поднимает/переиспользует процесс);
- на выходе на главный (rj-h0y-обработчик) — `POST /api/games/{id}/leave` (presence--).

Парно на каждое открытие экрана. Детализация — против фронт-кода (вне scope бэк-плана; завести под-задачу/учесть в rj-as6).

## Заметки исполнителю

- **Refcount под `registry_lock`:** `inflight`/`presence` инкрементятся в той же секции, что и выбор/создание слота (`_claim`) → kill (mark_absent/sweep) видит ненулевой счётчик и не трогает. Отдельного `busy`-флага после await НЕТ.
- **Два триггера:** `leave` (mark_absent: presence→0 && inflight==0) и idle-sweep (inflight==0 && idle>timeout, без гейта presence). + shutdown.
- **`last_activity`** двигает любое обращение к слоту (`_claim`/`_unclaim`/mark_present/mark_absent) — активная партия не реапится.
- **`RapfiAdapter`** (старый) остаётся ради helpers и `test_adapter.py`; приложение/`play_cli` — на реестре.
- **level_tag** — `level_id` engine-оппонента, только логи; `app.rapfi` не импортирует `app.game`.
- **Within-game undo (rj-t95)** этим планом НЕ лечится — отдельный форк-трек движка.
- **Логи — ручной префикс** `game=%s pid=%s` в каждом месседже (осознанное упрощение
  вместо `LoggerAdapter`/contextvar из §3.4 — проще, эквивалентно по выводу). Не искать
  LoggerAdapter.
- **`close()` зовётся ПОСЛЕ отмены всех `bg_tasks`** (порядок в lifespan: cancel bg →
  gather bg → cancel sweep → gather sweep → `close()`), поэтому in-flight `compute_move`
  к моменту `close()` нет — гонка `close`↔`_run.respawn` на `slot.proc` исключена порядком.
- **Внутри Task 7 контур-/service-тесты ожидаемо КРАСНЫЕ** между Step 3 и Step 10 (фейки
  правятся в Step 5/8) — это нормальный red→green в рамках задачи, не чинить преждевременно;
  зелёный набор сверять на Step 10.
- **`release()`** — API под удаление партии (rj-as6), в rj-899 не вызывается; покрыт
  `test_release_kills_idle` (idle-ветка; inflight>0-ранний-return структурно как в mark_absent).
- Тесты — **последовательно** (shared engine state в integration).
