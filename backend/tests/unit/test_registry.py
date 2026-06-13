import asyncio

import pytest

from app.domain.engine_params import EngineParams
from app.rapfi.registry import EngineRegistry

P = EngineParams(strength=50, timeout_turn_ms=200)


class FakeProc:
    """Фейк RapfiProcess: отдаёт заданные строки; пустой script → зависание (hang-тест)."""

    _seq = 1000

    def __init__(self, script):
        self._script = list(script)
        self.sent = []
        self._alive = True
        FakeProc._seq += 1
        self.pid = FakeProc._seq

    @property
    def alive(self):
        return self._alive

    async def send(self, lines):
        self.sent.append(lines)

    async def read_line(self):
        if not self._script:
            await asyncio.sleep(3600)  # hang
        return self._script.pop(0)

    async def terminate(self, *, grace_s):
        self._alive = False


def make_registry(spawn, **kw):
    d = dict(bin_path="/x", config_path="/y", cwd="/z", idle_timeout_s=100.0, kill_grace_s=0.01)
    d.update(kw)
    return EngineRegistry(spawn=spawn, **d)


# --- Task 3: claim/spawn/расчёт, дедуп, провал spawn ---


@pytest.mark.asyncio
async def test_compute_move_spawns_and_returns():
    spawned = []

    async def spawn(**kw):
        p = FakeProc(["MESSAGE loading", "7,8"])
        spawned.append(p)
        return p

    reg = make_registry(spawn)
    assert await reg.compute_move("g1", [(7, 7)], P) == (7, 8)
    assert len(spawned) == 1
    await reg.close()


@pytest.mark.asyncio
async def test_concurrent_compute_one_process():
    spawned = []

    async def spawn(**kw):
        await asyncio.sleep(0.02)
        p = FakeProc(["7,8", "7,9"])
        spawned.append(p)
        return p

    reg = make_registry(spawn)
    r = await asyncio.gather(reg.compute_move("g", [(7, 7)], P), reg.compute_move("g", [(7, 7)], P))
    assert len(spawned) == 1 and set(r) <= {(7, 8), (7, 9)}
    await reg.close()


@pytest.mark.asyncio
async def test_spawn_failure_clears_placeholder():
    n = {"i": 0}

    async def spawn(**kw):
        n["i"] += 1
        if n["i"] == 1:
            raise OSError("boom")
        return FakeProc(["7,8"])

    reg = make_registry(spawn)
    with pytest.raises(OSError):
        await reg.compute_move("g", [(7, 7)], P)
    assert await asyncio.wait_for(reg.compute_move("g", [(7, 7)], P), 2) == (7, 8)
    await reg.close()


# --- Task 4: presence (enter/leave), release ---


@pytest.mark.asyncio
async def test_enter_spawns_second_device_reuses():
    spawned = []

    async def spawn(**kw):
        p = FakeProc([])
        spawned.append(p)
        return p

    reg = make_registry(spawn)
    await reg.mark_present("g")  # устройство 1 → spawn
    await reg.mark_present("g")  # устройство 2 → переиспользует
    assert len(spawned) == 1 and reg._slots["g"].presence == 2
    await reg.close()


@pytest.mark.asyncio
async def test_last_leave_kills_not_last_keeps():
    procs = []

    async def spawn(**kw):
        p = FakeProc([])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.mark_present("g")
    await reg.mark_present("g")
    await reg.mark_absent("g")  # presence 2→1: не трогаем
    assert "g" in reg._slots and procs[0].alive
    await reg.mark_absent("g")  # presence 1→0: гасим
    assert "g" not in reg._slots and procs[0].alive is False
    await reg.close()


@pytest.mark.asyncio
async def test_leave_does_not_kill_during_compute():
    async def spawn(**kw):
        return FakeProc([])  # зависнет → inflight держится

    reg = make_registry(spawn)
    await reg.mark_present("g")
    task = asyncio.create_task(
        reg.compute_move("g", [(7, 7)], EngineParams(strength=1, timeout_turn_ms=5000))
    )
    await asyncio.sleep(0.05)  # inflight=1
    await reg.mark_absent("g")  # presence 1→0, но inflight>0 → НЕ гасим
    assert "g" in reg._slots
    task.cancel()
    await reg.close()


@pytest.mark.asyncio
async def test_release_kills_idle():  # API под удаление партии (rj-as6)
    procs = []

    async def spawn(**kw):
        p = FakeProc([])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.mark_present("g")
    await reg.release("g")  # inflight==0 → гасим
    assert "g" not in reg._slots and procs[0].alive is False
    await reg.close()


# --- Task 5: idle-sweep (без гейта presence) ---


@pytest.mark.asyncio
async def test_sweep_reaps_idle_regardless_of_presence():
    clock = {"t": 0.0}

    async def spawn(**kw):
        return FakeProc([])

    reg = make_registry(spawn, idle_timeout_s=10.0, now=lambda: clock["t"])
    await reg.mark_present("g")  # presence=1 (зависший «дрейф»)
    clock["t"] = 5.0
    await reg.sweep_once()
    assert "g" in reg._slots  # ещё активен
    clock["t"] = 20.0
    await reg.sweep_once()
    assert "g" not in reg._slots  # по простою реапнут, ХОТЯ presence>0
    await reg.close()


@pytest.mark.asyncio
async def test_sweep_skips_inflight():
    clock = {"t": 0.0}

    async def spawn(**kw):
        return FakeProc([])  # зависнет → inflight

    reg = make_registry(spawn, idle_timeout_s=1.0, now=lambda: clock["t"])
    task = asyncio.create_task(
        reg.compute_move("g", [(7, 7)], EngineParams(strength=1, timeout_turn_ms=5000))
    )
    await asyncio.sleep(0.05)
    clock["t"] = 100.0
    await reg.sweep_once()
    assert "g" in reg._slots  # inflight>0 → не реапим
    task.cancel()
    await reg.close()


# --- Task 6: лог-контракт ---


@pytest.mark.asyncio
async def test_logs_carry_game_and_pid(caplog):
    import logging

    async def spawn(**kw):
        return FakeProc(["7,8"])

    reg = make_registry(spawn)
    with caplog.at_level(logging.INFO, logger="renju.engine"):
        await reg.mark_present("game-xyz")
        await reg.compute_move("game-xyz", [(7, 7)], P)
        await reg.mark_absent("game-xyz")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "game-xyz" in text and "pid=" in text
    assert "spawn" in text and "compute_move" in text and "kill" in text
    await reg.close()
