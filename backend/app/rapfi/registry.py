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
from typing import Protocol

from ..domain.engine_params import EngineParams
from ..domain.values import Point
from .adapter import (
    _FORBID_PARAMS,
    _FORBID_TIMEOUT_S,
    _WALL_CLOCK_SLACK_S,
    EngineError,
    _move_commands,
    incremental_move_commands,
)
from .process import EngineProcessDied, RapfiProcess
from .protocol import (
    LineKind,
    ParsedLine,
    ProtocolError,
    forbid_commands,
    init_commands,
    parse_line,
    plan_sync,
)

_log = logging.getLogger("renju.engine")


class _EngineProc(Protocol):
    """Интерфейс процесса, который держит слот (RapfiProcess в проде, фейк в тестах)."""

    @property
    def alive(self) -> bool: ...
    @property
    def pid(self) -> int: ...
    async def send(self, lines: list[str]) -> None: ...
    async def read_line(self) -> str: ...
    async def terminate(self, *, grace_s: float) -> None: ...


SpawnFn = Callable[..., Awaitable[_EngineProc]]


@dataclass
class EngineSlot:
    proc: _EngineProc | None = None
    pid: int | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    io_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    inflight: int = 0  # идущие расчёты (защита от kill во время хода)
    presence: int = 0  # устройства, держащие партию открытой (гейтит триггер ВЫХОД)
    last_activity: float = 0.0
    level_tag: str = "-"
    synced: list[Point] | None = None  # позиция движка вкл. его ход; None = не инициализирован


class EngineRegistry:
    """Один процесс Rapfi на game_id. enter/leave/idle — сигналы извне; HTTP/SSE не знает."""

    def __init__(
        self,
        *,
        bin_path: Path,
        config_path: Path,
        cwd: Path,
        idle_timeout_s: float,
        kill_grace_s: float = 2.0,
        wall_clock_slack_s: float = _WALL_CLOCK_SLACK_S,
        spawn: SpawnFn = RapfiProcess.spawn,
        now: Callable[[], float] = time.monotonic,
    ):
        self._bin, self._config, self._cwd = bin_path, config_path, cwd
        self._idle, self._grace, self._slack = idle_timeout_s, kill_grace_s, wall_clock_slack_s
        self._spawn, self._now = spawn, now
        self._slots: dict[str, EngineSlot] = {}
        self._cond = asyncio.Condition()  # его lock = registry_lock
        self._closing = False

    async def compute_move(
        self,
        game_id: str,
        moves: Sequence[Point],
        params: EngineParams,
        allowed_zone: frozenset[Point] | None = None,
        *,
        level_tag: str = "-",
    ) -> Point:
        target: list[Point] = [(m[0], m[1]) for m in moves]  # нормализованный список Point
        timeout = params.timeout_turn_ms / 1000 + self._slack
        slot = await self._claim(game_id, level_tag, "inflight")
        t0 = self._now()  # после claim: ms = время расчёта, не spawn (spawn — своя лог-строка)
        try:
            parsed = await self._run_move(slot, game_id, target, params, allowed_zone, timeout)
        finally:
            await self._unclaim(slot, "inflight")
        ms = int((self._now() - t0) * 1000)
        if parsed.move is None:
            _log.warning("engine_invalid_move game=%s pid=%s reason=no-move", game_id, slot.pid)
            await self._reset_synced(slot)
            raise EngineError("engine returned no move")
        if parsed.move in set(target):
            _log.warning(
                "engine_invalid_move game=%s pid=%s move=%s reason=occupied",
                game_id,
                slot.pid,
                parsed.move,
            )
            await self._reset_synced(slot)
            raise EngineError(f"engine returned occupied cell: {parsed.move}")
        _log.info(
            "compute_move game=%s pid=%s moves=%d -> %s ms=%d",
            game_id,
            slot.pid,
            len(moves),
            parsed.move,
            ms,
        )
        return parsed.move

    async def forbidden_points(
        self, game_id: str, moves: Sequence[Point], *, level_tag: str = "-"
    ) -> list[Point]:
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
        _log.debug(
            "forbidden_points game=%s pid=%s moves=%d n=%d",
            game_id,
            slot.pid,
            len(moves),
            len(parsed.forbidden),
        )
        return list(parsed.forbidden)

    async def mark_present(self, game_id: str, level_tag: str = "-") -> None:
        """enter: presence++ (spawn если первый)."""
        await self._claim(game_id, level_tag, "presence")

    async def mark_absent(self, game_id: str, *, reason: str = "leave") -> None:
        """leave: presence-- (release если ушло последнее устройство и нет расчёта)."""
        victim = None
        async with self._cond:
            slot = self._slots.get(game_id)
            if slot is None or slot.presence == 0:
                return
            slot.presence -= 1
            slot.last_activity = self._now()
            if slot.presence == 0 and slot.inflight == 0:
                self._slots.pop(game_id, None)
                victim = slot
                self._cond.notify_all()
        if victim is not None:
            await self._terminate(victim, game_id, reason)

    async def release(self, game_id: str, *, reason: str = "delete") -> None:
        """Явное гашение (удаление партии, rj-as6). Не трогает идущий расчёт."""
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

    async def sweep_once(self) -> None:
        """idle-таймаут: реап по неактивности (inflight==0 && idle), БЕЗ гейта presence."""
        async with self._cond:
            victims = [
                (gid, s)
                for gid, s in self._slots.items()
                if s.inflight == 0 and self._now() - s.last_activity > self._idle
            ]
            for gid, _s in victims:
                self._slots.pop(gid, None)
            if victims:
                self._cond.notify_all()
        await asyncio.gather(
            *[self._terminate(s, gid, "idle") for gid, s in victims], return_exceptions=True
        )

    async def close(self) -> None:
        """shutdown: гасим все слоты (зовётся ПОСЛЕ отмены всех bg-advance → in-flight нет)."""
        async with self._cond:
            self._closing = True
            items = list(self._slots.items())
            self._slots.clear()
            self._cond.notify_all()
        await asyncio.gather(
            *[self._terminate(s, gid, "shutdown") for gid, s in items if s.proc],
            return_exceptions=True,
        )

    # --- claim/unclaim: get-or-create + counter под одним локом, затем spawn вне лока ---

    async def _claim(self, game_id: str, level_tag: str, counter: str) -> EngineSlot:
        while True:  # петля, не рекурсия: при провале создателя waiter пересоздаёт без роста стека
            async with self._cond:
                if self._closing:
                    raise EngineError("registry closing")
                existing = self._slots.get(game_id)
                if existing is None:
                    slot = EngineSlot(level_tag=level_tag, last_activity=self._now())
                    self._slots[game_id] = slot
                    creator = True
                else:
                    slot = existing
                    creator = False
                setattr(slot, counter, getattr(slot, counter) + 1)
                slot.last_activity = self._now()
            if creator:
                await self._spawn_into(game_id, slot, counter)
                return slot
            await slot.ready.wait()
            if slot.proc is not None:
                return slot
            await self._unclaim(slot, counter)  # создатель упал → снять заявку и ретрай (loop)

    async def _spawn_into(self, game_id: str, slot: EngineSlot, counter: str) -> None:
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
                orphan = proc  # реестр закрыт/слот изъят за время spawn
                setattr(slot, counter, getattr(slot, counter) - 1)
                slot.ready.set()
                self._cond.notify_all()
            else:
                slot.proc, slot.pid = proc, proc.pid
                slot.synced = None  # свежий процесс — состояние движка неизвестно
                slot.ready.set()
                _log.info("spawn game=%s pid=%s level_tag=%s", game_id, proc.pid, slot.level_tag)
        if orphan is not None:
            await orphan.terminate(grace_s=self._grace)
            raise EngineError("slot evicted during spawn (registry closing or recreated)")

    async def _unclaim(self, slot: EngineSlot, counter: str) -> None:
        async with self._cond:
            setattr(slot, counter, getattr(slot, counter) - 1)
            slot.last_activity = self._now()
            self._cond.notify_all()

    # --- расчёт на слоте (retry-once + respawn per-slot) ---

    async def _run(
        self, slot: EngineSlot, game_id: str, commands: list[str], want: LineKind, timeout_s: float
    ) -> ParsedLine:
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

    async def _attempt(
        self, slot: EngineSlot, game_id: str, commands: list[str], want: LineKind, timeout_s: float
    ) -> ParsedLine:
        if slot.proc is None or not slot.proc.alive:
            await self._respawn(slot, game_id, reason="dead")
        proc = slot.proc
        assert proc is not None  # _respawn выставил slot.proc
        async with asyncio.timeout(timeout_s):
            await proc.send(commands)
            return await self._read_until(proc, want)

    async def _read_until(self, proc: _EngineProc, want: LineKind) -> ParsedLine:
        """Дренаж строк до нужного типа. Вызывать под asyncio.timeout."""
        while True:
            parsed = parse_line(await proc.read_line())
            if parsed.kind is want:
                return parsed
            if parsed.kind is LineKind.ERROR:
                raise ProtocolError(parsed.text)

    # --- инкрементальный MOVE-путь ---

    async def _run_move(
        self,
        slot: EngineSlot,
        game_id: str,
        target: list[Point],
        params: EngineParams,
        allowed_zone: frozenset[Point] | None,
        timeout_s: float,
    ) -> ParsedLine:
        """retry-once обвязка для инкрементального хода."""
        async with slot.io_lock:
            try:
                return await self._attempt_move(
                    slot, game_id, target, params, allowed_zone, timeout_s
                )
            except (TimeoutError, EngineProcessDied, ProtocolError):
                await self._respawn(slot, game_id, reason="hang")
            try:
                return await self._attempt_move(
                    slot, game_id, target, params, allowed_zone, timeout_s
                )
            except (TimeoutError, EngineProcessDied, ProtocolError) as e:
                await self._respawn(slot, game_id, reason="hang")
                raise EngineError(f"engine failed twice: {e!r}") from e

    async def _attempt_move(
        self,
        slot: EngineSlot,
        game_id: str,
        target: list[Point],
        params: EngineParams,
        allowed_zone: frozenset[Point] | None,
        timeout_s: float,
    ) -> ParsedLine:
        """Один attempt: строим дельту от slot.synced, шлём, читаем ход, обновляем synced."""
        if slot.proc is None or not slot.proc.alive:
            await self._respawn(slot, game_id, reason="dead")  # сбросит synced=None
        plan = plan_sync(slot.synced, target)
        if plan.cold:
            cmds = _move_commands(target, params, allowed_zone)
        else:
            cmds = incremental_move_commands(
                plan, target=target, params=params, allowed_zone=allowed_zone
            )
        proc = slot.proc
        assert proc is not None  # _respawn выставил slot.proc
        async with asyncio.timeout(timeout_s):
            await proc.send(cmds)
            parsed = await self._read_until(proc, LineKind.MOVE)
        assert parsed.move is not None  # _read_until(MOVE) гарантирует ход
        slot.synced = [*target, parsed.move]
        return parsed

    async def _reset_synced(self, slot: EngineSlot) -> None:
        """Сброс synced под io_lock: следующий запрос пойдёт cold."""
        async with slot.io_lock:
            slot.synced = None

    async def _respawn(self, slot: EngineSlot, game_id: str, *, reason: str) -> None:
        if slot.proc is not None:  # лог смены pid (наблюдаемость respawn, §3.1/§7)
            _log.warning("kill game=%s pid=%s reason=%s", game_id, slot.pid, reason)
            await slot.proc.terminate(grace_s=self._grace)
        slot.proc = await self._spawn(bin_path=self._bin, config_path=self._config, cwd=self._cwd)
        slot.pid = slot.proc.pid
        slot.synced = None  # новый процесс — состояние движка неизвестно
        _log.info(
            "spawn game=%s pid=%s level_tag=%s reason=respawn", game_id, slot.pid, slot.level_tag
        )

    async def _terminate(self, slot: EngineSlot, game_id: str, reason: str) -> None:
        if slot.proc is not None:
            pid = slot.pid
            await slot.proc.terminate(grace_s=self._grace)
            slot.proc = None
            _log.info("kill game=%s pid=%s reason=%s", game_id, pid, reason)
