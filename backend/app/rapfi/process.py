"""OS-процесс Rapfi: spawn, обмен строками, завершение. Никакой логики протокола."""

import asyncio
from asyncio.subprocess import DEVNULL, PIPE
from pathlib import Path


class EngineProcessDied(Exception):
    """Процесс движка завершился/закрыл stdout."""


class RapfiProcess:
    def __init__(self, proc: asyncio.subprocess.Process):
        self._proc = proc

    @classmethod
    async def spawn(cls, *, bin_path: Path, config_path: Path, cwd: Path) -> "RapfiProcess":
        proc = await asyncio.create_subprocess_exec(
            str(bin_path),
            "--config",
            str(config_path),
            cwd=str(cwd),
            stdin=PIPE,
            stdout=PIPE,
            stderr=DEVNULL,
        )
        return cls(proc)

    @property
    def alive(self) -> bool:
        return self._proc.returncode is None

    @property
    def pid(self) -> int:
        return self._proc.pid

    async def send(self, lines: list[str]) -> None:
        if not lines:
            return
        if not self.alive:
            raise EngineProcessDied("send to dead engine process")
        if self._proc.stdin is None:
            raise EngineProcessDied("engine stdin is not a pipe")
        self._proc.stdin.write(("\n".join(lines) + "\n").encode())
        try:
            await self._proc.stdin.drain()
        except (ConnectionResetError, BrokenPipeError) as e:
            raise EngineProcessDied(str(e)) from e

    async def read_line(self) -> str:
        if self._proc.stdout is None:
            raise EngineProcessDied("engine stdout is not a pipe")
        raw = await self._proc.stdout.readline()
        if not raw:
            raise EngineProcessDied("engine stdout closed (EOF)")
        return raw.decode(errors="replace").strip()

    async def terminate(self, *, grace_s: float) -> None:
        """terminate → ждём grace_s → kill. Идемпотентно."""
        if not self.alive:
            return
        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=grace_s)
        except TimeoutError:
            self._proc.kill()
            await self._proc.wait()
