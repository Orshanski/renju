"""Замер: КУДА движок (БЕЛЫЕ) кладёт свой первый ход в ответ на чёрный центр.
Чистый raw, БЕЗ серверного кода, без зоны. Человек ЧЁРНЫМИ ставит центр (7,7) —
TURN на пустой доске, движок (белые) отвечает. Записываем его ход. N партий,
свежий процесс на каждую (незагрязнённый PRNG на силе 15). Распределение + сводка
по зонам RIF: 3×3 (чебышёв ≤1), 5×5 (≤2), вне 5×5 (>2).

Открытый вопрос дебюта: белый 2-й ход RIF требует в 3×3, а сам движок туда кладёт
лишь часть случаев — этот скрипт показывает, какую именно, без всякого YXBLOCK.
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

CENTER = (7, 7)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
STRENGTH = 15
TIMEOUT_MS = 1000
MOVE_RE = re.compile(r"^\d+,\d+$")


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


async def first_white(echo: bool = False) -> tuple[int, int]:
    proc = await spawn()
    try:
        await send(proc, ["START 15"], echo)
        await wait_ok(proc)
        await send(proc, ["INFO rule 4", f"INFO timeout_turn {TIMEOUT_MS}", f"INFO strength {STRENGTH}"], echo)
        await send(proc, [f"TURN {CENTER[0]},{CENTER[1]}"], echo)  # чёрный центр → движок (белый) отвечает
        return await read_move(proc)
    finally:
        if proc.stdin is not None:
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except (asyncio.TimeoutError, ProcessLookupError):
            proc.kill()


def cheb(p: tuple[int, int]) -> int:
    return max(abs(p[0] - CENTER[0]), abs(p[1] - CENTER[1]))


async def main():
    print(f"чёрный центр {CENTER} → первый ход движка (БЕЛЫЕ); сила {STRENGTH}, свежий процесс/партию, N={N}")
    print("первая партия печатает команды:")
    cnt: Counter = Counter()
    for k in range(N):
        e = await first_white(echo=(k == 0))
        cnt[e] += 1

    z3 = sum(c for p, c in cnt.items() if cheb(p) <= 1)
    z5 = sum(c for p, c in cnt.items() if cheb(p) == 2)
    out = sum(c for p, c in cnt.items() if cheb(p) > 2)

    print(f"\nраспределение первого белого хода ({len(cnt)} уникальных клеток):")
    for pos, c in sorted(cnt.items(), key=lambda kv: -kv[1]):
        print(f"  {pos}  d={cheb(pos)}  ×{c}")
    print("\nсводка по зонам RIF (чебышёв от центра):")
    print(f"  в 3×3 (d≤1):       {z3}/{N}")
    print(f"  в 5×5, но не 3×3 (d=2): {z5}/{N}")
    print(f"  вне 5×5 (d>2):     {out}/{N}")


if __name__ == "__main__":
    asyncio.run(main())
