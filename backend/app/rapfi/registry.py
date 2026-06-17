"""Реестр процессов Rapfi по game_id (rj-899). Один процесс на партию, изоляция.

Процесс живёт как матч в Piskvork-протоколе: инициализация один раз, дальше только
штатные инкрементальные команды. `START`/`BOARD`/`YXBOARD` допустимы только пока
`slot.synced is None`, то есть на свежем процессе.
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
    _FORBID_TIMEOUT_S,
    _WALL_CLOCK_SLACK_S,
    EngineError,
    _move_commands,
    incremental_move_commands,
)
from .engine_config_file import build_engine_config, remove_engine_config
from .process import EngineProcessDied, RapfiProcess
from .protocol import (
    LineKind,
    ParsedLine,
    ProtocolError,
    forbid_commands,
    hashclear_commands,
    parse_line,
    plan_sync,
    start_commands,
    takeback_commands,
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
    config_path: Path | None = None  # per-game TOML; None = использовать глобальный шаблон


class EngineRegistry:
    """Один процесс Rapfi на game_id. enter/leave/idle — сигналы извне; HTTP/SSE не знает."""

    def __init__(
        self,
        *,
        bin_path: Path,
        config_path: Path,
        cwd: Path,
        idle_timeout_s: float,
        data_dir: Path,
        kill_grace_s: float = 2.0,
        wall_clock_slack_s: float = _WALL_CLOCK_SLACK_S,
        spawn: SpawnFn = RapfiProcess.spawn,
        now: Callable[[], float] = time.monotonic,
    ):
        self._bin, self._config, self._cwd = bin_path, config_path, cwd
        self._data_dir = data_dir
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
        nnue: bool | None = None,
    ) -> Point:
        target: list[Point] = [(m[0], m[1]) for m in moves]  # нормализованный список Point
        timeout = params.timeout_turn_ms / 1000 + self._slack
        slot = await self._claim(game_id, level_tag, "inflight", nnue=nnue)
        t0 = self._now()  # после claim: ms = время расчёта, не spawn (spawn — своя лог-строка)
        try:
            parsed = await self._run_move(slot, game_id, target, params, allowed_zone, timeout)
        finally:
            await self._unclaim(slot, "inflight")
        ms = int((self._now() - t0) * 1000)
        if parsed.move is None:
            _log.warning("engine_invalid_move game=%s pid=%s reason=no-move", game_id, slot.pid)
            await self._discard_slot(game_id, slot, "invalid")
            raise EngineError("engine returned no move")
        if parsed.move in set(target):
            _log.warning(
                "engine_invalid_move game=%s pid=%s move=%s reason=occupied",
                game_id,
                slot.pid,
                parsed.move,
            )
            await self._discard_slot(game_id, slot, "invalid")
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
        self,
        game_id: str,
        moves: Sequence[Point],
        *,
        level_tag: str = "-",
        nnue: bool | None = None,
    ) -> list[Point]:
        if len(moves) % 2 != 0:
            return []
        target: list[Point] = [(m[0], m[1]) for m in moves]
        slot = await self._claim(game_id, level_tag, "inflight", nnue=nnue)
        try:
            parsed = await self._run_forbid(slot, game_id, target, _FORBID_TIMEOUT_S)
        finally:
            await self._unclaim(slot, "inflight")
        if parsed.forbidden is None:
            raise EngineError("engine returned no forbidden list")
        _log.debug(
            "forbidden_points game=%s pid=%s moves=%d n=%d",
            game_id,
            slot.pid,
            len(target),
            len(parsed.forbidden),
        )
        return list(parsed.forbidden)

    async def sync_after_undo(
        self, game_id: str, moves: Sequence[Point], *, level_tag: str = "-"
    ) -> None:
        """Undo-синхронизация живого процесса: только штатные TAKEBACK, без cold replay.

        Если процесса/слота нет — синхронизировать нечего. Если живой slot уже не
        сводится к target через снятие суффикса, slot считается испорченным и
        выбрасывается, чтобы не продолжать партию из неверной позиции.
        """
        target: list[Point] = [(m[0], m[1]) for m in moves]
        async with self._cond:
            slot = self._slots.get(game_id)
            if slot is None:
                _log.info("undo_sync game=%s skipped=no-slot target=%s", game_id, target)
                return
            slot.inflight += 1
            slot.last_activity = self._now()
        try:
            await slot.ready.wait()
            async with slot.io_lock:
                if slot.proc is None or not slot.proc.alive or slot.synced is None:
                    _log.info(
                        "undo_sync game=%s pid=%s skipped=not-ready target=%s synced=%s",
                        game_id,
                        slot.pid,
                        target,
                        slot.synced,
                    )
                    return
                if len(target) > len(slot.synced) or slot.synced[: len(target)] != target:
                    _log.warning(
                        "undo_sync game=%s pid=%s reason=desync target=%s synced=%s",
                        game_id,
                        slot.pid,
                        target,
                        slot.synced,
                    )
                    await self._discard_slot(game_id, slot, "undo-desync")
                    return
                takebacks = tuple(reversed(slot.synced[len(target) :]))
                if not takebacks:
                    _log.info(
                        "undo_sync game=%s pid=%s skipped=noop target=%s synced=%s",
                        game_id,
                        slot.pid,
                        target,
                        slot.synced,
                    )
                    return
                proc = slot.proc
                # YXHASHCLEAR ПОСЛЕ TAKEBACK: откат оставляет старый search/hash движка,
                # иначе следующий расчёт на той же позиции отвечает не как на свежей.
                cmds = [*takeback_commands(takebacks), *hashclear_commands()]
                _log.info(
                    "undo_sync game=%s pid=%s target=%s synced_before=%s cmds=%s",
                    game_id,
                    slot.pid,
                    target,
                    slot.synced,
                    cmds,
                )
                try:
                    async with asyncio.timeout(_FORBID_TIMEOUT_S):
                        await proc.send(cmds)
                        for _ in takebacks:
                            await self._read_until(proc, LineKind.OK)
                except (TimeoutError, EngineProcessDied, ProtocolError):
                    _log.warning(
                        "undo_sync game=%s pid=%s reason=failed target=%s synced_before=%s",
                        game_id,
                        slot.pid,
                        target,
                        slot.synced,
                    )
                    await self._discard_slot(game_id, slot, "undo-sync-failed")
                    return
                slot.synced = target
                _log.info(
                    "undo_sync game=%s pid=%s synced_after=%s",
                    game_id,
                    slot.pid,
                    slot.synced,
                )
        finally:
            await self._unclaim(slot, "inflight")

    async def mark_present(
        self, game_id: str, level_tag: str = "-", *, nnue: bool | None = None
    ) -> None:
        """enter: presence++ (spawn если первый)."""
        await self._claim(game_id, level_tag, "presence", nnue=nnue)

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
        """idle-таймаут: реап по неактивности (presence==0 && inflight==0 && idle)."""
        async with self._cond:
            victims = [
                (gid, s)
                for gid, s in self._slots.items()
                if s.presence == 0 and s.inflight == 0 and self._now() - s.last_activity > self._idle
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

    async def _claim(
        self, game_id: str, level_tag: str, counter: str, *, nnue: bool | None = None
    ) -> EngineSlot:
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
                await self._spawn_into(game_id, slot, counter, nnue=nnue)
                return slot
            await slot.ready.wait()
            if slot.proc is not None:
                return slot
            await self._unclaim(slot, counter)  # создатель упал → снять заявку и ретрай (loop)

    async def _spawn_into(
        self, game_id: str, slot: EngineSlot, counter: str, *, nnue: bool | None = None
    ) -> None:
        # Собираем per-game конфиг при первом спавне (immutable на сессию)
        if nnue is not None and slot.config_path is None:
            slot.config_path = build_engine_config(
                nnue=nnue,
                game_id=game_id,
                data_dir=self._data_dir,
                base=self._config.read_text(),
            )
        effective_config = slot.config_path if slot.config_path is not None else self._config
        try:
            proc = await self._spawn(
                bin_path=self._bin, config_path=effective_config, cwd=self._cwd
            )
        except BaseException:
            async with self._cond:
                setattr(slot, counter, getattr(slot, counter) - 1)
                self._slots.pop(game_id, None)
                slot.ready.set()
                self._cond.notify_all()
                # Спавн упал: слот изъят и до _terminate не дойдёт. Если МЫ собрали файл
                # в этот заход — убрать ПОД ЛОКОМ (атомарно с pop, без окна гонки), иначе он
                # осиротеет (на устойчивом сбое — вечная утечка).
                if slot.config_path is not None:
                    remove_engine_config(game_id, self._data_dir)
            raise
        orphan = None
        async with self._cond:
            if self._closing or self._slots.get(game_id) is not slot:
                orphan = proc  # реестр закрыт/слот изъят за время spawn
                setattr(slot, counter, getattr(slot, counter) - 1)
                slot.ready.set()
                self._cond.notify_all()
                # Слот не получит proc → close() его пропустит (гейт `if s.proc`), а _terminate
                # не вызовется. Убираем собранный файл ПОД ЛОКОМ (снимок _slots атомарен с unlink),
                # но только если его не перехватил НОВЫЙ слот того же game_id (recreate владеет тем
                # же именем и уберёт сам). КРИТИЧНО под локом, а НЕ после `await terminate` ниже:
                # иначе recreate в окне await успел бы записать файл, и мы снесли бы ЖИВОЙ конфиг.
                if slot.config_path is not None and (
                    self._closing or self._slots.get(game_id) is None
                ):
                    remove_engine_config(game_id, self._data_dir)
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

    # --- forbidden-путь (инкрементальный: warm=YXSHOWFORBID, cold=YXBOARD без think) ---

    async def _run_forbid(
        self, slot: EngineSlot, game_id: str, target: list[Point], timeout_s: float
    ) -> ParsedLine:
        """retry-once обвязка для инкрементального запроса фолов."""
        async with slot.io_lock:
            try:
                return await self._attempt_forbid(slot, game_id, target, timeout_s)
            except (TimeoutError, EngineProcessDied, ProtocolError):
                await self._respawn(slot, game_id, reason="hang")
            try:
                return await self._attempt_forbid(slot, game_id, target, timeout_s)
            except (TimeoutError, EngineProcessDied, ProtocolError) as e:
                await self._respawn(slot, game_id, reason="hang")
                raise EngineError(f"engine failed twice: {e!r}") from e

    async def _attempt_forbid(
        self, slot: EngineSlot, game_id: str, target: list[Point], timeout_s: float
    ) -> ParsedLine:
        """Один attempt: свежий процесс → YXBOARD; живой процесс → TAKEBACK*+YXSHOWFORBID."""
        if slot.proc is None or not slot.proc.alive:
            await self._respawn(slot, game_id, reason="dead")
        takebacks: tuple[Point, ...] | None = None
        if slot.synced is not None:
            n = 0
            while n < len(slot.synced) and n < len(target) and slot.synced[n] == target[n]:
                n += 1
            if n == len(target):
                takebacks = tuple(reversed(slot.synced[n:]))
            else:
                raise EngineError("engine state cannot be incrementally synced for forbidden")
        cmds = (
            [*takeback_commands(takebacks), "YXSHOWFORBID"]
            if takebacks is not None
            else [*start_commands(), *forbid_commands(target)]
        )
        proc = slot.proc
        assert proc is not None  # _respawn выставил slot.proc
        async with asyncio.timeout(timeout_s):
            await proc.send(cmds)
            parsed = await self._read_until(proc, LineKind.FORBID)
        if takebacks is not None or slot.synced != target:
            slot.synced = target  # forbid-путь не делает ход движка, только приводит позицию
        return parsed

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
        if plan.cold and slot.synced is not None:
            raise EngineError("engine state cannot be incrementally synced for move")
        if plan.cold:
            cmds = _move_commands(target, params, allowed_zone)
        else:
            cmds = incremental_move_commands(
                plan, target=target, params=params, allowed_zone=allowed_zone
            )
        proc = slot.proc
        assert proc is not None  # _respawn выставил slot.proc
        _log.info(
            "engine_cmd game=%s pid=%s target=%s synced_before=%s cmds=%s",
            game_id,
            slot.pid,
            target,
            slot.synced,
            cmds,
        )
        async with asyncio.timeout(timeout_s):
            await proc.send(cmds)
            parsed = await self._read_until(proc, LineKind.MOVE)
        assert parsed.move is not None  # _read_until(MOVE) гарантирует ход
        slot.synced = [*target, parsed.move]
        _log.info(
            "engine_cmd game=%s pid=%s move=%s synced_after=%s",
            game_id,
            slot.pid,
            parsed.move,
            slot.synced,
        )
        return parsed

    async def _respawn(self, slot: EngineSlot, game_id: str, *, reason: str) -> None:
        if slot.proc is not None:  # лог смены pid (наблюдаемость respawn, §3.1/§7)
            _log.warning("kill game=%s pid=%s reason=%s", game_id, slot.pid, reason)
            await slot.proc.terminate(grace_s=self._grace)
        effective_config = slot.config_path if slot.config_path is not None else self._config
        slot.proc = await self._spawn(
            bin_path=self._bin, config_path=effective_config, cwd=self._cwd
        )
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
        remove_engine_config(game_id, self._data_dir)  # best-effort; silent if missing

    async def _discard_slot(self, game_id: str, slot: EngineSlot, reason: str) -> None:
        """Убрать испорченный slot из реестра и завершить его процесс."""
        async with self._cond:
            if self._slots.get(game_id) is slot:
                self._slots.pop(game_id, None)
                self._cond.notify_all()
        await self._terminate(slot, game_id, reason)
