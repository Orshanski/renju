"""Замер силы: глубина поиска (MAX_DEPTH) против strength. Движок-vs-движок, винрейт.

Два вопроса:
  1) MAX_DEPTH реально режет глубину? — техпроверка: заданная глубина vs достигнутая
     (движок печатает "depth N-..." при SHOW_DETAIL).
  2) Глубина разводит силу уровней, в отличие от strength? — турнир round-robin,
     winrate по сетке настроек. Гипотеза: strength 0 и 5 неразличимы (рычаг не тот),
     а соседние глубины 1<2<3<4 дают явный градиент.

Вариативность: threads=1 → поиск детерминирован по позиции; варьируем первый ход
чёрных по центральной 3x3 (9 партий на конфиг). Судья — наш domain.outcome_after
(+ оверлайн чёрных = фол = победа белых; двойные тройки/четвёрки не ловим — редкий
край, движок rule-4 их сам избегает). Чистый raw-транспорт, app только для судьи/команд.

Запуск из backend/:  uv run python scripts/engine_probes/probe_depth_vs_strength_raw.py [check|tourney]
"""

import asyncio
import re
import sys
import time
from asyncio.subprocess import DEVNULL, PIPE
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.domain.rules import outcome_after  # noqa: E402
from app.domain.values import Color, GameStatus, color_of_move  # noqa: E402
from app.rapfi.protocol import position_commands, turn_commands  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "engine/rapfi/Rapfi/build/native/pbrain-rapfi"
CFG = ROOT / "engine/config.toml"
CWD = ROOT / "engine"

MOVE_RE = re.compile(r"^\d+,\d+$")
DEPTH_RE = re.compile(r"INFO DEPTH (\d+)")
NODES_RE = re.compile(r"INFO TOTALNODES (\d+)")
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]
OPENINGS = [(x, y) for x in (6, 7, 8) for y in (6, 7, 8)]  # первый ход чёрных, 3x3 центр
MAX_PLIES = 225


# ── транспорт ───────────────────────────────────────────────────────────────
class Eng:
    def __init__(self, proc):
        self.proc = proc
        self.primed = False


async def spawn(merge_err: bool = False) -> Eng:
    proc = await asyncio.create_subprocess_exec(
        str(BIN),
        "--config",
        str(CFG),
        cwd=str(CWD),
        stdin=PIPE,
        stdout=PIPE,
        stderr=asyncio.subprocess.STDOUT if merge_err else DEVNULL,
    )
    return Eng(proc)


async def send(eng: Eng, lines: list[str]) -> None:
    eng.proc.stdin.write(("\n".join(lines) + "\n").encode())
    await eng.proc.stdin.drain()


async def read_line(eng: Eng) -> str:
    raw = await eng.proc.stdout.readline()
    if not raw:
        raise RuntimeError("движок закрыл stdout (EOF)")
    return raw.decode(errors="replace").strip()


async def wait_ok(eng: Eng) -> None:
    while (await read_line(eng)) != "OK":
        pass


async def read_move(eng: Eng) -> tuple[int, int]:
    while True:
        ln = await read_line(eng)
        if MOVE_RE.match(ln):
            x, y = ln.split(",")
            return int(x), int(y)
        if ln.startswith("ERROR"):
            raise RuntimeError(ln)


async def kill(eng: Eng) -> None:
    if eng.proc.stdin is not None:
        eng.proc.stdin.close()
    try:
        await asyncio.wait_for(eng.proc.wait(), timeout=3)
    except (TimeoutError, ProcessLookupError):
        eng.proc.kill()


async def setup(eng: Eng, cfg: dict) -> None:
    await send(eng, ["START 15"])
    await wait_ok(eng)
    cmds = [
        "INFO rule 4",
        f"INFO timeout_turn {cfg['timeout']}",
        f"INFO strength {cfg['strength']}",
    ]
    if cfg.get("max_depth"):
        cmds.append(f"INFO max_depth {cfg['max_depth']}")
    if cfg.get("max_node"):
        cmds.append(f"INFO max_node {cfg['max_node']}")
    await send(eng, cmds)


# ── судья ─────────────────────────────────────────────────────────────────────
def _max_run(stones: set, last: tuple) -> int:
    best = 0
    for dx, dy in DIRS:
        c = 1
        x, y = last
        while (x + dx, y + dy) in stones:
            c += 1
            x, y = x + dx, y + dy
        x, y = last
        while (x - dx, y - dy) in stones:
            c += 1
            x, y = x - dx, y - dy
        best = max(best, c)
    return best


def judge(moves: list) -> GameStatus | None:
    st = outcome_after(moves)
    if st is not None:
        return st
    if color_of_move(len(moves) - 1) is Color.BLACK:
        own = {moves[i] for i in range(len(moves)) if color_of_move(i) is Color.BLACK}
        if _max_run(own, moves[-1]) > 5:  # оверлайн чёрных = фол
            return GameStatus.FINISHED_WHITE
    return None


# ── одна партия: cfg_b чёрными, cfg_w белыми, навязанный первый ход ────────────
async def ask(eng: Eng, moves: list) -> tuple[int, int]:
    # BOARD…DONE сам провоцирует ход движка (это и есть запрос хода) — без YXNBEST.
    if not eng.primed:
        await send(eng, position_commands(moves))
        eng.primed = True
    else:
        await send(eng, turn_commands(moves[-1]))
    return await asyncio.wait_for(read_move(eng), timeout=90)


async def play(cfg_b: dict, cfg_w: dict, first: tuple) -> GameStatus:
    pb, pw = await spawn(), await spawn()
    try:
        await setup(pb, cfg_b)
        await setup(pw, cfg_w)
        moves = [first]
        while len(moves) < MAX_PLIES:
            eng = pw if len(moves) % 2 == 1 else pb  # нечётная длина → ход белых
            mv = await ask(eng, moves)
            if mv in set(moves):  # занятая клетка — считаем поражением сходившего
                return (
                    GameStatus.FINISHED_WHITE
                    if len(moves) % 2 == 0
                    else GameStatus.FINISHED_BLACK
                )
            moves.append(mv)
            st = judge(moves)
            if st is not None:
                return st
        return GameStatus.FINISHED_DRAW
    finally:
        await kill(pb)
        await kill(pw)


# ── режим 1: техпроверка применения MAX_DEPTH ─────────────────────────────────
async def check() -> None:
    pos = [(7, 7), (7, 8), (8, 8), (6, 8), (8, 7), (6, 6)]  # середина партии, ход чёрных
    print("Техпроверка: задаём MAX_DEPTH, читаем реально достигнутую глубину\n")
    print(f"{'задано':>8} {'достигнуто':>11} {'время,мс':>9}")
    for d in (1, 2, 3, 4, 8, 99):
        eng = await spawn()
        try:
            await setup(eng, {"strength": 100, "timeout": 30000, "max_depth": d})
            await send(eng, ["INFO show_detail 2", *position_commands(pos), "YXNBEST 1"])
            reached, t0 = 0, time.monotonic()
            while True:
                ln = await read_line(eng)
                if m := DEPTH_RE.search(ln):
                    reached = max(reached, int(m.group(1)))
                if MOVE_RE.match(ln):
                    break
                if ln.startswith("ERROR"):
                    raise RuntimeError(ln)
            ms = int((time.monotonic() - t0) * 1000)
            print(f"{d:>8} {reached:>11} {ms:>9}")
        finally:
            await kill(eng)


# ── режим 2: турнир винрейтов ─────────────────────────────────────────────────
def depth_cfg(d: int) -> dict:
    return {"strength": 100, "timeout": 30000, "max_depth": d}  # strength 100 → skill off


def strength_cfg(s: int) -> dict:
    return {"strength": s, "timeout": 30000}  # max_depth по умолчанию 99 → рулит strength


async def match(name_a: str, cfg_a: dict, name_b: str, cfg_b: dict) -> None:
    """A и B играют оба openings обоими цветами; винрейт A (ничьи отдельно)."""
    wa = wb = draw = 0
    for first in OPENINGS:
        st = await play(cfg_a, cfg_b, first)  # A чёрные
        wa += st is GameStatus.FINISHED_BLACK
        wb += st is GameStatus.FINISHED_WHITE
        draw += st is GameStatus.FINISHED_DRAW
        st = await play(cfg_b, cfg_a, first)  # A белые
        wb += st is GameStatus.FINISHED_BLACK
        wa += st is GameStatus.FINISHED_WHITE
        draw += st is GameStatus.FINISHED_DRAW
    n = len(OPENINGS) * 2
    print(f"  {name_a:>10} vs {name_b:<10}: {name_a} {wa}/{n}  {name_b} {wb}/{n}  ничьих {draw}")


async def tourney() -> None:
    print("=== ГЛУБИНА: соседние и крайние пары (strength=100, skill off) ===")
    for a, b in [(1, 2), (2, 3), (3, 4), (4, 8), (1, 8)]:
        await match(f"d{a}", depth_cfg(a), f"d{b}", depth_cfg(b))
    print("\n=== STRENGTH: тот же замер на старом рычаге (max_depth=99) ===")
    for a, b in [(0, 5), (0, 15), (5, 15)]:
        await match(f"s{a}", strength_cfg(a), f"s{b}", strength_cfg(b))


async def baseline() -> None:
    """Изолированно: сколько УЗЛОВ берёт движок на ход САМ, без силовых ограничений
    (strength=100, без max_depth/max_node). Время даём с запасом (не лимит) — узлы от
    железа не зависят, а реальное время покажет, сошёлся ли движок сам («мухой») или
    упёрся в запас. Главная метрика — узлы и достигнутая глубина."""
    positions = {
        "1-й ход (пустая)": [],
        "дебют (5 камней)": [(7, 7), (7, 8), (8, 8), (6, 8), (8, 7)],
        "миттельшпиль (10)": [
            (7, 7), (7, 8), (8, 8), (6, 8), (8, 7),
            (6, 6), (9, 9), (8, 9), (9, 7), (7, 6),
        ],
    }
    budget_ms = 2000  # реалистичное игровое время на ход; реально,мс покажет, упёрся ли
    print(f"strength=100, БЕЗ max_depth/max_node, время {budget_ms} мс/ход.")
    print(f"{'позиция':<20} {'глубина':>8} {'узлов':>14} {'реально,мс':>11}")
    for name, pos in positions.items():
        eng = await spawn()
        try:
            await setup(eng, {"strength": 100, "timeout": budget_ms})  # без max_depth/max_node
            board = position_commands(pos) if pos else ["BEGIN"]
            await send(eng, ["INFO show_detail 2", *board])
            depth = nodes = 0
            t0 = time.monotonic()
            while True:
                ln = await read_line(eng)
                if m := DEPTH_RE.search(ln):
                    depth = max(depth, int(m.group(1)))
                if m := NODES_RE.search(ln):
                    nodes = max(nodes, int(m.group(1)))
                if MOVE_RE.match(ln):
                    break
                if ln.startswith("ERROR"):
                    raise RuntimeError(ln)
            ms = int((time.monotonic() - t0) * 1000)
            print(f"{name:<20} {depth:>8} {nodes:>14,} {ms:>11,}")
        finally:
            await kill(eng)


async def dump() -> None:
    """Сырой вывод движка (stdout+stderr) на одном ходу: понять формат строк глубины."""
    pos = [(7, 7), (7, 8), (8, 8), (6, 8), (8, 7), (6, 6)]
    eng = await spawn(merge_err=True)
    try:
        await setup(eng, {"strength": 100, "timeout": 4000, "max_depth": 10})
        await send(eng, ["INFO show_detail 3", *position_commands(pos), "YXNBEST 1"])
        while True:
            ln = await read_line(eng)
            print(repr(ln))
            if MOVE_RE.match(ln):
                break
    finally:
        await kill(eng)


async def noise(a: int, b: int, n: int) -> None:
    """Большая выборка s{a} vs s{b}: шум или реальная разница? Чередуем цвет/дебют."""
    ca, cb = strength_cfg(a), strength_cfg(b)
    wa = wb = draw = 0
    print(f"s{a} vs s{b}, цель n={n} (промежуточно каждые 20):", flush=True)
    for k in range(n):
        first = OPENINGS[k % len(OPENINGS)]
        if k % 2 == 0:  # A чёрные
            st = await play(ca, cb, first)
            wa += st is GameStatus.FINISHED_BLACK
            wb += st is GameStatus.FINISHED_WHITE
        else:  # A белые
            st = await play(cb, ca, first)
            wb += st is GameStatus.FINISHED_BLACK
            wa += st is GameStatus.FINISHED_WHITE
        draw += st is GameStatus.FINISHED_DRAW
        if (k + 1) % 20 == 0:
            done = k + 1
            print(
                f"  {done:>3}: s{a} {wa} ({100 * wa / done:.0f}%)  "
                f"s{b} {wb} ({100 * wb / done:.0f}%)  ничьих {draw}",
                flush=True,
            )
    print(f"\nИТОГ s{a} vs s{b}, n={n}: s{a} {wa}  s{b} {wb}  ничьих {draw}")


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "baseline":
        await baseline()
    elif mode == "noise":
        a = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        b = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 200
        await noise(a, b, n)
    elif mode == "dump":
        await dump()
    elif mode == "check":
        await check()
    elif mode == "tourney":
        await tourney()
    else:
        await check()
        print()
        await tourney()


if __name__ == "__main__":
    asyncio.run(main())
