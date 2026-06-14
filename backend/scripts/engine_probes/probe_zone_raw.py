"""ЧИСТЫЙ поиск алгоритма управления движком. БЕЗ серверного кода (ноль импортов
из app): свой транспорт через asyncio.create_subprocess_exec, сырой протокол
Piskvork/yx руками, YXBLOCK формируется и шлётся ПРЯМО ЗДЕСЬ — видно в коде и в выводе.

Сетап = проигрышная партия из лога: движок ЧЁРНЫМИ. Первый ход движок ставит САМ
(BEGIN, свободно — изолируем эффект зоны, НЕ примешивая навязанный центр). Человек
БЕЛЫМИ тянет прямую (8,7)(9,7)(10,7)(11,7)(12,7). Движок обязан вклиниться. Два
режима, единственное отличие — YXBLOCK 5×5 на 3-м ходу движка:
  BEZ  — никакого YXBLOCK;
  ZONE — перед TURN 3-го хода шлём YXBLOCK(все свободные клетки вне 5×5)…DONE, после — YXBLOCKRESET.
Свежий процесс на КАЖДУЮ партию (сила 15 варьирует — нужен незагрязнённый PRNG).
Метрика — свои правила (5 в ряд; чёрным ровно 5, белым ≥5), посчитана здесь же.
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

HUMAN = [(8, 7), (9, 7), (10, 7), (11, 7), (12, 7)]  # прямая линия белых из лога
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100  # число партий
STRENGTH = 15
TIMEOUT_MS = 1000
MOVE_RE = re.compile(r"^\d+,\d+$")
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]


# ── зона и YXBLOCK (формируем руками) ───────────────────────────────────────
def zone_5x5() -> set[tuple[int, int]]:
    """Центральный 5×5: центр (7,7), радиус 2 → x,y ∈ [5..9]."""
    return {(x, y) for x in range(5, 10) for y in range(5, 10)}


def yxblock_lines(occupied: set[tuple[int, int]]) -> list[str]:
    """YXBLOCK = все свободные клетки доски ВНЕ зоны 5×5. Это и есть «ограничить зоной»."""
    zone = zone_5x5()
    cells = [
        (x, y)
        for x in range(15)
        for y in range(15)
        if (x, y) not in zone and (x, y) not in occupied
    ]
    return ["YXBLOCK", *[f"{x},{y}" for x, y in cells], "DONE"]


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
        print("    →", " | ".join(lines if len(lines) <= 6 else [*lines[:4], f"...(+{len(lines) - 5} строк)...", lines[-1]]))
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


# ── одна партия: BEGIN (свободный 1-й ход) + YXBLOCK 5×5 на 3-м ходу ─────────
async def one_game(echo: bool = False) -> tuple[str, list[tuple[int, int]]]:
    proc = await spawn()
    try:
        await send(proc, ["START 15"], echo)
        await wait_ok(proc)
        await send(proc, ["INFO rule 4", f"INFO timeout_turn {TIMEOUT_MS}", f"INFO strength {STRENGTH}"], echo)
        await send(proc, ["BEGIN"], echo)
        e1 = await read_move(proc)  # движок САМ ставит первый ход (свободно, без навязывания)
        moves: list[tuple[int, int]] = [e1]
        black: set[tuple[int, int]] = {e1}
        white: set[tuple[int, int]] = set()
        for i, w in enumerate(HUMAN):
            if w in black:  # движок превентивно занял клетку линии
                return "перехватил", moves
            white.add(w)
            moves = moves + [w]
            if made_five(white, w, exactly=False):
                return "СЛИЛ", moves
            if i < len(HUMAN) - 1:  # на последний белый ход движок не отвечает
                cmds: list[str] = []
                if i == 0:  # ответ на 1-й белый = 3-й ход движка → зона 5×5
                    cmds += yxblock_lines(set(moves))
                cmds += [f"TURN {w[0]},{w[1]}"]
                if i == 0:
                    cmds += ["YXBLOCKRESET"]
                await send(proc, cmds, echo)
                e = await read_move(proc)
                black.add(e)
                moves = moves + [e]
                if made_five(black, e, exactly=True):
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
    print(f"движок ЧЁРНЫМИ, 1-й ход СВОБОДНО (BEGIN), зона 5×5 на 3-м; белые тянут {HUMAN}")
    print("первая партия печатает реальные команды (видно YXBLOCK):")
    res = Counter()
    sample = {}
    for k in range(N):
        outcome, moves = await one_game(echo=(k == 0))  # первую партию — с эхом команд
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
