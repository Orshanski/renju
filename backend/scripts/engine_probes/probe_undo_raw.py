"""Проверка МЕХАНИЗМА ОТКАТА. Чистый raw, БЕЗ серверного кода (ноль импортов из app):
свой транспорт, сырой протокол руками. Зоны/YXBLOCK НЕТ нигде.

Сценарий на свежем процессе:
  1) BEGIN — движок ЧЁРНЫМИ ставит первый ход САМ;
  2) строим линию белых до ТРОЙКИ (8,7)(9,7)(10,7), движок отвечает обычным TURN;
  3) TAKEBACK до первого хода (снимаем всё, кроме первого камня движка);
  4) очистки: YXHASHCLEAR (TT). Блока не было → YXBLOCKRESET не нужен;
  5) заново строим ту же линию белых, проверяем — перехватит или сольёт.

Контроль — probe_free_raw.py (без отката) перехватывал 100/100. Тут единственное
добавление — цикл отката с очисткой. Если после отката тоже 100/100 перехват — откат
чист; если посыплется в слив — ломает сам откат (важно: наш серверный undo делает
ровно TAKEBACK+YXHASHCLEAR). Метрика — свои правила, посчитана здесь же.
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
TRIPLE = HUMAN[:3]  # «тройка белых», до которой доводим перед откатом
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
    while True:
        ln = await read_line(proc)
        if ln == "OK":
            return
        if ln.startswith("ERROR"):
            raise RuntimeError(ln)


async def read_move(proc) -> tuple[int, int]:
    while True:
        ln = await read_line(proc)
        if MOVE_RE.match(ln):
            x, y = ln.split(",")
            return int(x), int(y)
        if ln.startswith("ERROR"):
            raise RuntimeError(ln)


# ── одна партия: построить тройку → откатить до 1-го → очистка → отстроить заново ─
async def one_game(echo: bool = False) -> tuple[str, list[tuple[int, int]]]:
    proc = await spawn()
    try:
        await send(proc, ["START 15"], echo)
        await wait_ok(proc)
        await send(proc, ["INFO rule 4", f"INFO timeout_turn {TIMEOUT_MS}", f"INFO strength {STRENGTH}"], echo)
        await send(proc, ["BEGIN"], echo)
        e1 = await read_move(proc)  # движок САМ ставит первый ход

        # ── ФАЗА 1: довести до тройки белых (без зоны, обычный TURN) ──
        moves: list[tuple[int, int]] = [e1]
        black: set[tuple[int, int]] = {e1}
        for w in TRIPLE:
            if w in black:  # движок занял клетку линии уже на построении (редко) — партия мимо цели
                return "вклинился_до_отката", moves
            moves = moves + [w]
            await send(proc, [f"TURN {w[0]},{w[1]}"], echo)
            e = await read_move(proc)
            black.add(e)
            moves = moves + [e]

        # ── ФАЗА 2: откат до первого хода (оставить только e1) ──
        for _ in range(len(moves) - 1):
            await send(proc, ["TAKEBACK 0,0"], echo)
            await wait_ok(proc)

        # ── ФАЗА 3: очистки (после отката — обязательно чистим TT) ──
        await send(proc, ["YXHASHCLEAR"], echo)  # MESSAGE, не OK — отфильтруется в read_move

        # ── ФАЗА 4: заново строим ту же линию, проверяем перехват ──
        moves = [e1]
        black = {e1}
        white: set[tuple[int, int]] = set()
        for i, w in enumerate(HUMAN):
            if w in black:
                return "перехватил", moves
            white.add(w)
            moves = moves + [w]
            if made_five(white, w, exactly=False):
                return "СЛИЛ", moves
            if i < len(HUMAN) - 1:
                await send(proc, [f"TURN {w[0]},{w[1]}"], echo)
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
    print(f"ОТКАТ: тройка белых {TRIPLE} → TAKEBACK до 1-го → YXHASHCLEAR → заново линия {HUMAN}")
    print("первая партия печатает реальные команды (видно TAKEBACK/YXHASHCLEAR):")
    res = Counter()
    sample = {}
    for k in range(N):
        outcome, moves = await one_game(echo=(k == 0))
        res[outcome] += 1
        sample.setdefault(outcome, moves)
    print(f"\nсвежий процесс/партию, сила {STRENGTH}, N={N}")
    print(f"  ПЕРЕХВАТИЛ:          {res['перехватил']}/{N}")
    print(f"  СЛИЛ:                {res['СЛИЛ']}/{N}")
    if res["вклинился_до_отката"]:
        print(f"  (вклинился до отката: {res['вклинился_до_отката']}/{N} — мимо цели)")
    if "СЛИЛ" in sample:
        print(f"    пример слива:  {sample['СЛИЛ']}")
    if "перехватил" in sample:
        print(f"    пример защиты: {sample['перехватил']}")


if __name__ == "__main__":
    asyncio.run(main())
