"""БЕЛЫЕ + ЗОНА + ОТКАТ + повторная линия. Чистый raw, БЕЗ серверного кода.
Движок БЕЛЫМИ, человек ЧЁРНЫМИ тянет прямую (7,7)(8,7)(9,7)(10,7)(11,7). На ПЕРВЫЙ
ход белых (ответ на чёрный центр) — YXBLOCK 3×3 (зона RIF для 2-го хода партии).

Сценарий на свежем процессе:
  1) построить до ТРОЙКИ чёрных (7,7)(8,7)(9,7), движок отвечает; на 1-й белый — зона 3×3;
  2) TAKEBACK до пустой доски (снять все ходы);
  3) очистка: YXHASHCLEAR;
  4) заново строить ВСЮ линию, снова с зоной 3×3 на 1-й белый, проверить — перехватит/сольёт.

Без зоны+отката (probe_black_line_raw) и с зоной без отката (probe_black_line_zone_raw)
движок белыми держал 100/100. Тут смотрим связку «зона + откат» в роли белых.
Метрика — свои правила. Свежий процесс на партию, сила 15.
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
TRIPLE = BLACK[:3]  # до тройки чёрных доводим перед откатом
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
STRENGTH = 15
TIMEOUT_MS = 1000
MOVE_RE = re.compile(r"^\d+,\d+$")
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]


def zone_3x3() -> set[tuple[int, int]]:
    """Центральный 3×3: центр (7,7), радиус 1 → x,y ∈ [6..8]. Зона RIF для 2-го хода."""
    return {(x, y) for x in range(6, 9) for y in range(6, 9)}


def yxblock_lines(occupied: set[tuple[int, int]]) -> list[str]:
    """YXBLOCK = все свободные клетки доски ВНЕ зоны 3×3."""
    zone = zone_3x3()
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


async def white_reply(proc, b, first_white: bool, occupied: set, echo: bool) -> tuple[int, int]:
    """Ход чёрного b → ответ движка (белый). На первый белый — зона 3×3 (YXBLOCK/RESET вокруг TURN)."""
    cmds: list[str] = []
    if first_white:
        cmds += yxblock_lines(occupied)
    cmds += [f"TURN {b[0]},{b[1]}"]
    if first_white:
        cmds += ["YXBLOCKRESET"]
    await send(proc, cmds, echo)
    return await read_move(proc)


# ── одна партия: построить тройку → откатить до пустой → очистка → отстроить заново ─
async def one_game(echo: bool = False) -> tuple[str, list[tuple[int, int]]]:
    proc = await spawn()
    try:
        await send(proc, ["START 15"], echo)
        await wait_ok(proc)
        await send(proc, ["INFO rule 4", f"INFO timeout_turn {TIMEOUT_MS}", f"INFO strength {STRENGTH}"], echo)

        # ── ФАЗА 1: построить до тройки чёрных (движок белыми, зона на 1-й белый) ──
        # Движок белыми может вклиниться в линию уже здесь — тогда прерываем построение
        # на достигнутом (непустой истории для отката достаточно), не шлём TURN на занятую.
        moves: list[tuple[int, int]] = []
        n_white = 0
        for b in TRIPLE:
            if b in set(moves):  # движок занял эту клетку линии — дальше не строим
                break
            moves = moves + [b]
            e = await white_reply(proc, b, n_white == 0, set(moves), echo)
            n_white += 1
            moves = moves + [e]

        # ── ФАЗА 2: откат до пустой доски ──
        for _ in range(len(moves)):
            await send(proc, ["TAKEBACK 0,0"], echo)
            await wait_ok(proc)

        # ── ФАЗА 3: очистка ──
        await send(proc, ["YXHASHCLEAR"], echo)

        # ── ФАЗА 4: заново вся линия, снова зона на 1-й белый, проверка ──
        moves = []
        black: set[tuple[int, int]] = set()
        white: set[tuple[int, int]] = set()
        n_white = 0
        for i, b in enumerate(BLACK):
            if b in white:
                return "перехватил", moves
            black.add(b)
            moves = moves + [b]
            if made_five(black, b, exactly=True):
                return "СЛИЛ", moves
            if i < len(BLACK) - 1:
                e = await white_reply(proc, b, n_white == 0, set(moves), echo)
                n_white += 1
                white.add(e)
                moves = moves + [e]
                if made_five(white, e, exactly=False):
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
    print(f"БЕЛЫЕ + зона 3×3 на 1-й белый + откат до пустой + YXHASHCLEAR + заново; чёрные тянут {BLACK}")
    print("первая партия печатает реальные команды (видно YXBLOCK/TAKEBACK/YXHASHCLEAR):")
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
