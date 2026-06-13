"""Консольная партия против Rapfi через наш адаптер. Ручной smoke этапа 1.

Запуск:  cd backend && uv run python -m scripts.play_cli --level medium
Ввод:    ход — буква+число (h8); u — undo; q — выход.
"""

import argparse
import asyncio
import random
import string

from app.config import REPO_ROOT, Settings
from app.domain.game import undo_truncate
from app.domain.opening import opening_zone
from app.domain.rules import outcome_after
from app.domain.values import (
    BOARD_SIZE,
    Color,
    DomainError,
    Point,
    color_to_move,
)
from app.game_service import apply_move, engine_move, new_game
from app.levels_config import LevelInfo, load_levels, resolve_level
from app.rapfi.registry import EngineRegistry

_COLS = string.ascii_lowercase[:BOARD_SIZE]  # a..o


def parse_input(raw: str) -> Point | None:
    s = raw.strip().lower()
    if len(s) < 2 or s[0] not in _COLS or not s[1:].isdigit():
        return None
    x = _COLS.index(s[0])
    y = int(s[1:]) - 1
    if not (0 <= y < BOARD_SIZE):
        return None
    return (x, y)


def render_board(
    *, moves: list[Point], forbidden: list[Point], zone: frozenset[Point] | None = None
) -> str:
    stones: dict[Point, str] = {}
    for i, p in enumerate(moves):
        stones[p] = "●" if i % 2 == 0 else "○"
    for p in forbidden:
        stones.setdefault(p, "×")
    if zone is not None:
        for p in zone:
            stones.setdefault(p, "+")  # только свободные клетки зоны
    rows = []
    for y in range(BOARD_SIZE - 1, -1, -1):
        cells = " ".join(stones.get((x, y), "·") for x in range(BOARD_SIZE))
        rows.append(f"{y + 1:>2} {cells}")
    rows.append("   " + " ".join(_COLS))
    return "\n".join(rows)


async def game_loop(level: LevelInfo) -> None:
    settings = Settings()
    adapter = EngineRegistry(
        bin_path=settings.resolved_rapfi_bin(),
        config_path=settings.rapfi_config,
        cwd=REPO_ROOT,
        idle_timeout_s=600.0,
        kill_grace_s=settings.engine_kill_grace_s,
    )
    params = level.params
    human = random.choice([Color.BLACK, Color.WHITE])
    colour = "чёрными ●" if human is Color.BLACK else "белыми ○"
    print(f"Уровень: {level.name}. Ты играешь {colour}.")
    moves: list[Point] = new_game()
    try:
        while True:
            forbidden = await adapter.forbidden_points("cli", moves)  # фолы чёрных
            human_turn = color_to_move(len(moves)) is human
            zone = opening_zone(len(moves)) if human_turn else None
            print(render_board(moves=moves, forbidden=forbidden, zone=zone))

            if not human_turn:
                print("… соперник думает")
                engine_pt = await engine_move(adapter, moves, params, "cli", level.id)
                moves = apply_move(moves, engine_pt, forbidden=forbidden)
                outcome = outcome_after(moves)
                if outcome is not None:
                    print(render_board(moves=moves, forbidden=[]))
                    print(f"Партия окончена: {outcome.value}")
                    return
                continue

            raw = input("Твой ход (h8 / u / q): ")
            if raw.strip().lower() == "q":
                return
            if raw.strip().lower() == "u":
                try:
                    moves = undo_truncate(moves=moves, for_color=human)
                except DomainError as e:
                    print(f"Undo нельзя: {e}")
                continue
            point = parse_input(raw)
            if point is None:
                print("Не понял. Пример: h8")
                continue
            try:
                moves = apply_move(moves, point, forbidden=forbidden)
            except DomainError as e:
                print(f"Ход отвергнут: {e}")
                continue
            outcome = outcome_after(moves)
            if outcome is not None:
                print(render_board(moves=moves, forbidden=[]))
                print(f"Партия окончена: {outcome.value}")
                return
    finally:
        await adapter.close()


def main() -> None:
    settings = Settings()
    levels = load_levels(settings.levels_file)  # пустой набор → ValueError
    ids = [lv.id for lv in levels]
    parser = argparse.ArgumentParser(description="Партия против Rapfi в терминале")
    parser.add_argument("--level", choices=ids, default=ids[0])
    args = parser.parse_args()
    level = resolve_level(levels, args.level)
    if level is None:  # choices гарантируют валидность; страховка
        parser.error(f"unknown level: {args.level}")
    asyncio.run(game_loop(level))


if __name__ == "__main__":
    main()
