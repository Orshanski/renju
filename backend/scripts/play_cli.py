"""Консольная партия против Rapfi через наш адаптер. Ручной smoke этапа 1.

Запуск:  cd backend && uv run python -m scripts.play_cli --level medium
Ввод:    ход — буква+число (h8); u — undo; q — выход.
"""

import argparse
import asyncio
import random
import string

from app.config import REPO_ROOT, Settings
from app.domain.game import undo_truncate, validate_human_move
from app.domain.levels import LEVELS, Level
from app.domain.rules import outcome_after
from app.domain.values import (
    BOARD_SIZE,
    Color,
    DomainError,
    GameStatus,
    Point,
    color_to_move,
)
from app.rapfi.adapter import RapfiAdapter

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


def render_board(*, moves: list[Point], forbidden: list[Point]) -> str:
    stones: dict[Point, str] = {}
    for i, p in enumerate(moves):
        stones[p] = "●" if i % 2 == 0 else "○"
    for p in forbidden:
        stones.setdefault(p, "×")
    rows = []
    for y in range(BOARD_SIZE - 1, -1, -1):
        cells = " ".join(stones.get((x, y), "·") for x in range(BOARD_SIZE))
        rows.append(f"{y + 1:>2} {cells}")
    rows.append("   " + " ".join(_COLS))
    return "\n".join(rows)


async def game_loop(level: Level) -> None:
    settings = Settings()
    adapter = RapfiAdapter(
        bin_path=settings.resolved_rapfi_bin(),
        config_path=settings.rapfi_config,
        cwd=REPO_ROOT,
    )
    params = LEVELS[level]
    human = random.choice([Color.BLACK, Color.WHITE])
    colour = "чёрными ●" if human is Color.BLACK else "белыми ○"
    print(f"Уровень: {level.value}. Ты играешь {colour}.")
    moves: list[Point] = []
    try:
        while True:
            if color_to_move(len(moves)) is not human:
                print("… соперник думает")
                engine_move = await adapter.compute_move(moves, params)
                moves.append(engine_move)
                outcome = outcome_after(moves)
                if outcome is not None:
                    print(render_board(moves=moves, forbidden=[]))
                    print(f"Партия окончена: {outcome.value}")
                    return
                continue

            forbidden = await adapter.forbidden_points(moves) if human is Color.BLACK else []
            print(render_board(moves=moves, forbidden=forbidden))
            raw = input("Твой ход (h8 / u / q): ")
            if raw.strip().lower() == "q":
                return
            if raw.strip().lower() == "u":
                try:
                    moves = undo_truncate(moves=moves, human_color=human)
                except DomainError as e:
                    print(f"Undo нельзя: {e}")
                continue
            point = parse_input(raw)
            if point is None:
                print("Не понял. Пример: h8")
                continue
            try:
                validate_human_move(
                    moves=moves,
                    human_color=human,
                    status=GameStatus.AWAITING_HUMAN,
                    point=point,
                    forbidden=forbidden,
                )
            except DomainError as e:
                print(f"Ход отвергнут: {e}")
                continue
            moves.append(point)
            outcome = outcome_after(moves)
            if outcome is not None:
                print(render_board(moves=moves, forbidden=[]))
                print(f"Партия окончена: {outcome.value}")
                return
    finally:
        await adapter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Партия против Rapfi в терминале")
    parser.add_argument("--level", choices=[lv.value for lv in Level], default=Level.MEDIUM.value)
    args = parser.parse_args()
    asyncio.run(game_loop(Level(args.level)))


if __name__ == "__main__":
    main()
