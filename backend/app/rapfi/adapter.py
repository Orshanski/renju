"""Фасад движка: «дай ход» и «дай фолы». Владеет процессом Rapfi.

Гарантии:
- одновременно выполняется не больше одного расчёта (asyncio.Lock);
- перед каждым расчётом движок переинициализируется (START/INFO/позиция);
- зависший или умерший процесс убивается по wall-clock таймауту и
  пересоздаётся; запрос повторяется один раз, дальше — EngineError.
"""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from app.domain.engine_params import EngineParams
from app.domain.values import Point
from app.rapfi.process import EngineProcessDied, RapfiProcess
from app.rapfi.protocol import (
    LineKind,
    ParsedLine,
    ProtocolError,
    forbid_commands,
    init_commands,
    parse_line,
    position_commands,
)

# Сколько добавить к timeout_turn движка до wall-clock kill: движок укладывается
# в свой бюджет сам, запас покрывает инициализацию (загрузку весов) и парсинг.
_WALL_CLOCK_SLACK_S = 5.0
_FORBID_TIMEOUT_S = 10.0
_FORBID_PARAMS = EngineParams(strength=100, timeout_turn_ms=1000)


class EngineError(Exception):
    """Движок не смог посчитать (после повтора). Несёт текст причины."""


class RapfiAdapter:
    def __init__(
        self,
        *,
        bin_path: Path,
        config_path: Path,
        cwd: Path,
        kill_grace_s: float = 2.0,
        wall_clock_slack_s: float = _WALL_CLOCK_SLACK_S,
    ):
        self._bin_path = bin_path
        self._config_path = config_path
        self._cwd = cwd
        self._kill_grace_s = kill_grace_s
        self._wall_clock_slack_s = wall_clock_slack_s
        self._lock = asyncio.Lock()
        self._proc: RapfiProcess | None = None

    async def compute_move(self, moves: Sequence[Point], params: EngineParams) -> Point:
        """Ход движка для позиции. Позиция — полный список ходов партии."""
        commands = init_commands(params) + position_commands(moves)
        timeout = params.timeout_turn_ms / 1000 + self._wall_clock_slack_s
        async with self._lock:
            parsed = await self._request(commands, LineKind.MOVE, timeout)
        if parsed.move is None:
            raise EngineError("engine returned no move")
        if parsed.move in set(moves):
            raise EngineError(f"engine returned occupied cell: {parsed.move}")
        return parsed.move

    async def forbidden_points(self, moves: Sequence[Point]) -> list[Point]:
        """Запрещённые точки для чёрных. Непусто только когда ход чёрных."""
        if len(moves) % 2 != 0:
            return []
        commands = init_commands(_FORBID_PARAMS) + forbid_commands(moves)
        async with self._lock:
            parsed = await self._request(commands, LineKind.FORBID, _FORBID_TIMEOUT_S)
        if parsed.forbidden is None:
            raise EngineError("engine returned no forbidden list")
        return list(parsed.forbidden)

    async def close(self) -> None:
        async with self._lock:
            if self._proc is not None:
                await self._proc.terminate(grace_s=self._kill_grace_s)
                self._proc = None

    # --- внутреннее -----------------------------------------------------

    async def _request(self, commands: list[str], want: LineKind, timeout_s: float) -> ParsedLine:
        """Одна попытка + один повтор на свежем процессе. Вызывать под self._lock."""
        try:
            return await self._attempt(commands, want, timeout_s)
        except (TimeoutError, EngineProcessDied, ProtocolError):
            await self._kill_proc()
        try:
            return await self._attempt(commands, want, timeout_s)
        except (TimeoutError, EngineProcessDied, ProtocolError) as e:
            await self._kill_proc()
            raise EngineError(f"engine failed twice: {e!r}") from e

    async def _attempt(self, commands: list[str], want: LineKind, timeout_s: float) -> ParsedLine:
        # spawn намеренно вне asyncio.timeout: create_subprocess_exec не блокирует
        # (веса грузятся лениво на первой stdin-команде, уже под таймаутом ниже).
        # Не переносить блокирующую работу в _ensure_proc — сбежит от wall-clock.
        proc = await self._ensure_proc()
        async with asyncio.timeout(timeout_s):
            await proc.send(commands)
            while True:
                parsed = parse_line(await proc.read_line())
                if parsed.kind is want:
                    return parsed
                if parsed.kind is LineKind.ERROR:
                    raise ProtocolError(parsed.text)

    async def _ensure_proc(self) -> RapfiProcess:
        if self._proc is None or not self._proc.alive:
            self._proc = await RapfiProcess.spawn(
                bin_path=self._bin_path, config_path=self._config_path, cwd=self._cwd
            )
        return self._proc

    async def _kill_proc(self) -> None:
        if self._proc is not None:
            await self._proc.terminate(grace_s=self._kill_grace_s)
            self._proc = None
