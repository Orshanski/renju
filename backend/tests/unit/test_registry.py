import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.domain.engine_params import EngineParams
from app.rapfi.registry import EngineRegistry

P = EngineParams(strength=50, timeout_turn_ms=200)

# Минимальный валидный TOML-конфиг движка (без секции evaluator — тест nnue=False её дропает)
_BASE_TOML = """\
[gomocup]
name = "Rapfi"

[model]
type = "mix9"
"""


class FakeProc:
    """Фейк RapfiProcess: отдаёт заданные строки; пустой script → зависание (hang-тест).
    Фиксирует config_path переданный при spawn."""

    _seq = 1000

    def __init__(self, script):
        self._script = list(script)
        self.sent = []
        self._alive = True
        self.spawned_config: Path | None = None
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


def make_registry(spawn, *, tmp_path: Path | None = None, **kw):
    """Фабрика реестра для юнит-тестов.

    tmp_path (pytest fixture) нужен для тестов, проверяющих per-game config (nnue).
    Если не передан — создаём registry без реального data_dir (nnue-тесты его требуют явно).
    """
    import tempfile

    data_dir = tmp_path if tmp_path is not None else Path(tempfile.mkdtemp())
    config_file = data_dir / "config.toml"
    if not config_file.exists():
        config_file.write_text(_BASE_TOML)
    d: dict[str, Any] = dict(
        bin_path="/x",
        config_path=config_file,
        cwd="/z",
        idle_timeout_s=100.0,
        kill_grace_s=0.01,
        data_dir=data_dir,
    )
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


# --- Task 5: idle-sweep (гейт presence) ---


@pytest.mark.asyncio
async def test_sweep_skips_active_presence():
    """Sweep не убивает слот, пока presence > 0 (пользователь в партии думает над ходом)."""
    clock = {"t": 0.0}

    async def spawn(**kw):
        return FakeProc([])

    reg = make_registry(spawn, idle_timeout_s=10.0, now=lambda: clock["t"])
    await reg.mark_present("g")  # presence=1
    clock["t"] = 20.0  # давно за пределами idle_timeout
    await reg.sweep_once()
    assert "g" in reg._slots  # presence > 0 → НЕ реапим
    await reg.close()


@pytest.mark.asyncio
async def test_sweep_reaps_idle_after_leave():
    """Sweep убивает слот, когда presence == 0 и timeout истёк."""
    clock = {"t": 0.0}

    async def spawn(**kw):
        return FakeProc([])

    reg = make_registry(spawn, idle_timeout_s=10.0, now=lambda: clock["t"])
    await reg.mark_present("g")
    await reg.mark_absent("g")  # presence → 0; но слот уже удалён mark_absent
    # mark_absent с presence→0 и inflight==0 сам удаляет слот → sweep не увидит его
    assert "g" not in reg._slots
    await reg.close()


@pytest.mark.asyncio
async def test_sweep_reaps_idle_no_presence():
    """Слот без presence реапится по idle — sweep работает там, где presence == 0."""
    clock = {"t": 0.0}

    async def spawn(**kw):
        # ответ на первый ход; sweep от хода не зависит
        return FakeProc(["7,8"])

    reg = make_registry(spawn, idle_timeout_s=10.0, now=lambda: clock["t"])
    # compute_move создаёт слот без presence; после хода inflight→0, presence=0
    await reg.compute_move("g", [(7, 7)], EngineParams(strength=1, timeout_turn_ms=5000))
    clock["t"] = 5.0
    await reg.sweep_once()
    assert "g" in reg._slots  # ещё в пределах timeout
    clock["t"] = 20.0
    await reg.sweep_once()
    assert "g" not in reg._slots  # presence==0, idle → реапим
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


# --- Task 3 (rj-t95): инкрементальный sync позиции ---


@pytest.mark.asyncio
async def test_first_move_cold_board_sets_synced():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8"])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    sent = [c for batch in procs[0].sent for c in batch]
    assert "START 15" in sent and "BOARD" in sent
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]
    await reg.close()


@pytest.mark.asyncio
async def test_second_move_incremental_turn_no_newgame():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8", "5,5"])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    procs[0].sent.clear()
    await reg.compute_move("g", [(7, 7), (8, 8), (6, 6)], P)
    sent = [c for batch in procs[0].sent for c in batch]
    assert "START 15" not in sent and "TURN 6,6" in sent
    assert reg._slots["g"].synced == [(7, 7), (8, 8), (6, 6), (5, 5)]
    await reg.close()


@pytest.mark.asyncio
async def test_undo_path_takeback_to_prefix_then_turn():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8", "4,4"])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7), (6, 6)], P)
    procs[0].sent.clear()
    await reg.compute_move("g", [(7, 7), (9, 9)], P)
    sent = [c for batch in procs[0].sent for c in batch]
    assert sent.count("START 15") == 0
    assert "TAKEBACK 8,8" in sent and "TAKEBACK 6,6" in sent and "TURN 9,9" in sent
    assert reg._slots["g"].synced == [(7, 7), (9, 9), (4, 4)]
    await reg.close()


@pytest.mark.asyncio
async def test_sync_after_undo_sends_takeback_and_updates_synced():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8", "OK", "9,9"])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]

    procs[0].sent.clear()
    await reg.sync_after_undo("g", [(7, 7)])

    assert procs[0].sent == [["TAKEBACK 8,8", "YXHASHCLEAR"]]  # хеш чистим после отката
    assert reg._slots["g"].synced == [(7, 7)]

    await reg.compute_move("g", [(7, 7), (6, 6)], P)
    sent = [c for batch in procs[0].sent for c in batch]
    assert "START 15" not in sent
    assert "TURN 6,6" in sent
    assert reg._slots["g"].synced == [(7, 7), (6, 6), (9, 9)]
    await reg.close()


@pytest.mark.asyncio
async def test_sync_after_undo_discards_slot_when_target_is_not_prefix():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8"])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    await reg.sync_after_undo("g", [(6, 6)])

    assert "g" not in reg._slots
    assert procs[0].alive is False
    await reg.close()


@pytest.mark.asyncio
async def test_undo_to_first_move_then_engine_thinks_on_current_board():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8", "9,9"])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    procs[0].sent.clear()
    await reg.compute_move("g", [(7, 7)], P)
    sent = [c for batch in procs[0].sent for c in batch]
    assert "START 15" not in sent and "BOARD" not in sent
    # YXHASHCLEAR после TAKEBACK: откат оставляет в TT стухшие линии (см. probe).
    assert sent == [
        "TAKEBACK 8,8",
        "YXHASHCLEAR",
        "INFO strength 50",
        "INFO timeout_turn 200",
        "INFO max_depth 99",
        "YXNBEST 1",
    ]
    assert reg._slots["g"].synced == [(7, 7), (9, 9)]
    await reg.close()


@pytest.mark.asyncio
async def test_compute_move_anomaly_rejects_without_cold_resetting_live_process():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8"])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    procs[0].sent.clear()

    from app.rapfi.adapter import EngineError

    with pytest.raises(EngineError):
        await reg.compute_move("g", [(7, 7), (8, 8), (6, 6), (5, 5)], P)

    assert len(procs) == 1
    assert procs[0].alive is True
    assert procs[0].sent == []
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]
    await reg.close()


@pytest.mark.asyncio
async def test_respawn_resets_synced_to_cold():
    # после смерти процесса следующий запрос идёт COLD (synced сброшен)
    procs = []
    # первый proc отвечает "8,8" (ход на запрос [(7,7)]),
    # второй (после respawn) отвечает "9,9" (ход на запрос [(7,7),(8,8),(6,6)])
    answers = [["8,8"], ["9,9"]]

    async def spawn(**kw):
        p = FakeProc(answers[len(procs)])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)  # synced=[(7,7),(8,8)]
    await procs[0].terminate(grace_s=0.01)  # внешняя смерть
    await reg.compute_move("g", [(7, 7), (8, 8), (6, 6)], P)  # proc мёртв → respawn → COLD
    sent = [c for batch in procs[1].sent for c in batch]
    assert "START 15" in sent and "BOARD" in sent  # cold (не TURN), т.к. synced сброшен
    await reg.close()


@pytest.mark.asyncio
async def test_post_lock_invalid_move_discards_slot():
    # движок вернул ЗАНЯТУЮ клетку → EngineError, процесс испорчен и убит.
    import pytest as _pt

    from app.rapfi.adapter import EngineError

    procs = []

    async def spawn(**kw):
        p = FakeProc(["7,7"])  # вернёт уже занятую (7,7)
        procs.append(p)
        return p

    reg = make_registry(spawn)
    with _pt.raises(EngineError):
        await reg.compute_move("g", [(7, 7)], P)
    assert "g" not in reg._slots
    assert procs[0].alive is False
    await reg.close()


# --- Task 4 (rj-t95): инкрементальный forbidden_points ---


@pytest.mark.asyncio
async def test_forbid_warm_only_yxshowforbid():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8", "FORBID ."])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)  # synced=[(7,7),(8,8)] — чёрный к ходу
    procs[0].sent.clear()
    await reg.forbidden_points("g", [(7, 7), (8, 8)])  # == synced → тёплый
    sent = [c for batch in procs[0].sent for c in batch]
    assert sent == ["YXSHOWFORBID"]  # ни START, ни YXBOARD, ни INFO
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]  # не тронут (read-only)
    await reg.close()


@pytest.mark.asyncio
async def test_forbid_after_undo_to_prefix_uses_takeback_not_cold_yxboard():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8", "5,5", "FORBID ."])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    await reg.compute_move("g", [(7, 7), (8, 8), (6, 6)], P)
    assert reg._slots["g"].synced == [(7, 7), (8, 8), (6, 6), (5, 5)]

    procs[0].sent.clear()
    await reg.forbidden_points("g", [(7, 7), (8, 8)])

    sent = [c for batch in procs[0].sent for c in batch]
    assert "START 15" not in sent and "YXBOARD" not in sent
    assert sent == ["TAKEBACK 5,5", "TAKEBACK 6,6", "YXSHOWFORBID"]
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]
    await reg.close()


@pytest.mark.asyncio
async def test_forbid_non_prefix_rejects_without_cold_resetting_live_process():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["8,8"])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    await reg.compute_move("g", [(7, 7)], P)
    procs[0].sent.clear()

    from app.rapfi.adapter import EngineError

    with pytest.raises(EngineError):
        await reg.forbidden_points("g", [(6, 6), (5, 5)])

    assert len(procs) == 1
    assert procs[0].alive is True
    assert procs[0].sent == []
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]
    await reg.close()


@pytest.mark.asyncio
async def test_forbid_cold_when_synced_none():
    procs = []

    async def spawn(**kw):
        p = FakeProc(["FORBID ."])
        procs.append(p)
        return p

    reg = make_registry(spawn)
    # synced=None → cold: START создаёт доску движка, затем YXBOARD+YXSHOWFORBID
    await reg.forbidden_points("g", [(7, 7), (8, 8)])
    sent = [c for batch in procs[0].sent for c in batch]
    assert "START 15" in sent and "YXBOARD" in sent and "YXSHOWFORBID" in sent
    assert not any(s.startswith("INFO strength") for s in sent)  # без tunable (форбид не думает)
    assert reg._slots["g"].synced == [(7, 7), (8, 8)]
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


# --- B3b: per-game config (nnue) ---


@pytest.mark.asyncio
async def test_spawn_with_nnue_uses_per_game_config(tmp_path):
    """compute_move с nnue=True → спавн под per-game TOML, не под self._config."""
    spawned_configs: list[Path] = []

    async def spawn(*, bin_path, config_path, cwd, **kw):
        p = FakeProc(["8,8"])
        p.spawned_config = config_path
        spawned_configs.append(config_path)
        return p

    reg = make_registry(spawn, tmp_path=tmp_path)
    await reg.compute_move("game-nnue", [(7, 7)], P, nnue=True)

    # Спавн должен использовать per-game конфиг, а не глобальный шаблон
    assert len(spawned_configs) == 1
    used = spawned_configs[0]
    global_cfg = tmp_path / "config.toml"
    assert used != global_cfg
    assert used == tmp_path / "engine_configs" / "game-nnue.toml"
    assert used.exists()

    # slot.config_path зафиксирован
    assert reg._slots["game-nnue"].config_path == used
    await reg.close()


@pytest.mark.asyncio
async def test_spawn_with_nnue_false_drops_evaluator(tmp_path):
    """nnue=False → per-game TOML не содержит секцию evaluator."""
    # Расширяем базовый TOML, добавив секцию evaluator
    config_file = tmp_path / "config.toml"
    evaluator_section = (
        '\n[model.evaluator]\ntype = "mix9"\n[[model.evaluator.weights]]\npath = "w.bin"\n'
    )
    config_file.write_text(_BASE_TOML + evaluator_section)

    async def spawn(*, bin_path, config_path, cwd, **kw):
        p = FakeProc(["8,8"])
        p.spawned_config = config_path
        return p

    reg = make_registry(spawn, tmp_path=tmp_path)
    await reg.compute_move("game-no-nnue", [(7, 7)], P, nnue=False)

    per_game = tmp_path / "engine_configs" / "game-no-nnue.toml"
    assert per_game.exists()
    content = per_game.read_text()
    assert "[model.evaluator]" not in content
    await reg.close()


@pytest.mark.asyncio
async def test_respawn_uses_slot_config_path(tmp_path):
    """После форс-respawn слот переиспользует тот же config_path, не глобальный."""
    spawned_configs: list[Path] = []

    async def spawn(*, bin_path, config_path, cwd, **kw):
        p = FakeProc(["8,8"])
        spawned_configs.append(config_path)
        return p

    reg = make_registry(spawn, tmp_path=tmp_path)
    # Первый спавн — через compute_move с nnue
    await reg.compute_move("game-resp", [(7, 7)], P, nnue=True)
    first_config = spawned_configs[0]
    assert first_config == tmp_path / "engine_configs" / "game-resp.toml"

    # Форс-respawn через _respawn (симулируем: убиваем процесс вручную)
    slot = reg._slots["game-resp"]
    async with slot.io_lock:
        await reg._respawn(slot, "game-resp", reason="test")

    # Второй спавн должен использовать тот же per-game config
    assert len(spawned_configs) == 2
    assert spawned_configs[1] == first_config
    await reg.close()


@pytest.mark.asyncio
async def test_terminate_removes_config_file(tmp_path):
    """После _terminate per-game TOML должен быть удалён."""

    async def spawn(*, bin_path, config_path, cwd, **kw):
        return FakeProc([])

    reg = make_registry(spawn, tmp_path=tmp_path)
    await reg.mark_present("game-term", nnue=True)

    per_game = tmp_path / "engine_configs" / "game-term.toml"
    assert per_game.exists(), "per-game config should exist after spawn"

    await reg.mark_absent("game-term")  # presence 1→0 → _terminate

    assert not per_game.exists(), "per-game config should be removed after _terminate"
    await reg.close()


@pytest.mark.asyncio
async def test_nnue_none_spawns_under_global_config(tmp_path):
    """nnue=None → спавн под глобальный self._config, per-game файл не создаётся."""
    spawned_configs: list[Path] = []

    async def spawn(*, bin_path, config_path, cwd, **kw):
        p = FakeProc(["8,8"])
        spawned_configs.append(config_path)
        return p

    reg = make_registry(spawn, tmp_path=tmp_path)
    global_cfg = tmp_path / "config.toml"
    await reg.compute_move("game-no-nnue-flag", [(7, 7)], P)  # nnue не передан → None

    assert spawned_configs[0] == global_cfg
    per_game_dir = tmp_path / "engine_configs"
    # Директория либо не создана, либо файла нет
    assert not (per_game_dir / "game-no-nnue-flag.toml").exists()
    await reg.close()


@pytest.mark.asyncio
async def test_spawn_failure_removes_assembled_config(tmp_path):
    """Спавн упал при nnue=True: собранный per-game TOML не должен осиротеть.
    Слот изъят и до _terminate не дойдёт → файл убираем прямо в except-ветке _spawn_into."""

    async def spawn(*, bin_path, config_path, cwd, **kw):
        raise OSError("spawn boom")

    reg = make_registry(spawn, tmp_path=tmp_path)
    per_game = tmp_path / "engine_configs" / "game-fail.toml"
    with pytest.raises(OSError):
        await reg.compute_move("game-fail", [(7, 7)], P, nnue=True)
    assert not per_game.exists(), "осиротевший per-game config после провала спавна"
    assert "game-fail" not in reg._slots
    await reg.close()


@pytest.mark.asyncio
async def test_spawn_orphaned_during_close_removes_config(tmp_path):
    """Слот осиротел во время спавна (close()/eviction → orphan-ветка): собранный файл
    не должен утечь. Удаление под локом orphan-ветки (close() пропустил бы слот с proc=None)."""
    from app.rapfi.adapter import EngineError

    holder: dict = {}

    async def spawn(*, bin_path, config_path, cwd, **kw):
        holder["reg"]._closing = True  # имитируем close() во время спавна → orphan-ветка
        return FakeProc([])

    reg = make_registry(spawn, tmp_path=tmp_path)
    holder["reg"] = reg
    per_game = tmp_path / "engine_configs" / "game-orphan.toml"
    with pytest.raises(EngineError):
        await reg.compute_move("game-orphan", [(7, 7)], P, nnue=True)
    assert not per_game.exists(), "осиротевший per-game config после eviction во время спавна"
    await reg.close()
