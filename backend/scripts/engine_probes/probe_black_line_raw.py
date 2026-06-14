"""ЗЕРКАЛО probe_free_raw.py: роли наоборот. Человек ЧЁРНЫМИ строит прямую линию
(ходит первым), движок — БЕЛЫЕ (отвечает вторым, обязан защищаться). Чистый raw,
БЕЗ серверного кода. Без навязанного первого хода, без зоны. Сила 15 (варьирует).

Движок белыми ходит вторым ⇒ НИКАКОГО BEGIN: первый чёрный ход человека уходит
обычным TURN на пустой доске, движок принимает его как ход соперника и отвечает белым.
Человек тянет прямую чёрную (7,7)(8,7)(9,7)(10,7)(11,7), движок должен вклиниться.

Метрика — свои правила: чёрные построили РОВНО 5 (оверлайн не победа) ⇒ движок СЛИЛ;
движок занял клетку линии или собрал свою ≥5 ⇒ перехватил. Свежий процесс на партию.
"""

import asyncio
import re
import sys
from asyncio.subprocess import DEVNULL, PIPE
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "engine/rapfi/Rapfi/build/native/pbrain-rapfi"
CFG = ROOT / "engine/config.toml"
CWD = ROOT / "engine"

BLACK = [(7, 7), (8, 7), (9, 7), (10, 7), (11, 7)]  # прямая ЧЁРНАЯ линия (человек), центр первым
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
STRENGTH = 15
TIMEOUT_MS = 1000
MOVE_RE = re.compile(r"^\d+,\d+$")
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]


def made_five(stones: set[tuple[int, int]], last: tuple[int, int], exactly: bool) -> bool:
    """5 в ряд через last. exactly=True (чёрные): ровно 5 (оверлайн не победа); иначе ≥5."""
    for dx, dy in DIRS:
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


# ── транспорт (свой, без app) ───────────────────────────────────────────────
async def spawn():
    return await asyncio.create_subprocess_exec(
        str(BIN), "--config", str(CFG), cwd=str(CWD), stdin=PIPE, stdout=PIPE, stderr=DEVNULL
    )


async def send(proc, lines: list[str], echo: bool = False):
    if echo:
        print("    →", " | ".join(lines))
    proc.stdin.write(("\n".join(lines) + "\n").encode())
    await proc.stdin.drain()


async def read_line(proc) -> str:
    raw = await proc.stdout.readline()
    if not raw:
        raise RuntimeError("движок закрыл stdout (EOF)")
    return raw.decode(errors="replace").strip()


async def wait_ok(proc):
    while (await read_line(proc)) != "OK":
        pass


async def read_move(proc) -> tuple[int, int]:
    while True:
        ln = await read_line(proc)
        if MOVE_RE.match(ln):
            x, y = ln.split(",")
            return int(x), int(y)
        if ln.startswith("ERROR"):
            raise RuntimeError(ln)


# ── одна партия: человек ЧЁРНЫМИ тянет линию, движок БЕЛЫМИ отвечает (без BEGIN) ─
async def one_game(echo: bool = False) -> tuple[str, list[tuple[int, int]]]:
    proc = await spawn()
    try:
        await send(proc, ["START 15"], echo)
        await wait_ok(proc)
        await send(proc, ["INFO rule 4", f"INFO timeout_turn {TIMEOUT_MS}", f"INFO strength {STRENGTH}"], echo)
        # без BEGIN: движок белыми, ходит вторым
        moves: list[tuple[int, int]] = []
        black: set[tuple[int, int]] = set()  # человек
        white: set[tuple[int, int]] = set()  # движок
        for i, b in enumerate(BLACK):
            if b in white:  # движок (белый) превентивно занял клетку линии
                return "перехватил", moves
            black.add(b)
            moves = moves + [b]
            if made_five(black, b, exactly=True):  # чёрные собрали ровно 5 → движок зевнул
                return "СЛИЛ", moves
            if i < len(BLACK) - 1:  # на последний чёрный движок не отвечает
                await send(proc, [f"TURN {b[0]},{b[1]}"], echo)  # ход чёрного-соперника → движок отвечает белым
                e = await read_move(proc)
                white.add(e)
                moves = moves + [e]
                if made_five(white, e, exactly=False):  # движок построил свою ≥5
                    return "перехватил", moves
        return "перехватил", moves
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except (asyncio.TimeoutError, ProcessLookupError):
            proc.kill()


async def main():
    print(f"движок БЕЛЫМИ (ходит вторым, без BEGIN); человек ЧЁРНЫМИ тянет {BLACK}")
    print("первая партия печатает реальные команды (нет BEGIN, сразу TURN):")
    res = Counter()
    sample = {}
    for k in range(N):
        outcome, moves = await one_game(echo=(k == 0))
        res[outcome] += 1
        sample.setdefault(outcome, moves)
    print(f"\nсвежий процесс/партию, сила {STRENGTH}, N={N}")
    print(f"  ПЕРЕХВАТИЛ: {res['перехватил']}/{N}")
    print(f"  СЛИЛ:       {res['СЛИЛ']}/{N}")
    if "СЛИЛ" in sample:
        print(f"    пример слива:  {sample['СЛИЛ']}")
    if "перехватил" in sample:
        print(f"    пример защиты: {sample['перехватил']}")


if __name__ == "__main__":
    asyncio.run(main())
