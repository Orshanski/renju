"""Загрузка уровней сложности из TOML. config-слой (I/O), не домен (§4.9)."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.domain.engine_params import EngineParams


@dataclass(frozen=True)
class LevelInfo:
    id: str
    name: str
    params: EngineParams


def load_levels(path: Path) -> list[LevelInfo]:
    """TOML-файл уровней → упорядоченный список (порядок записей = порядок уровней).

    Плоские поля записи (strength/timeout_turn_ms) собираются в EngineParams.
    Пустой набор → ValueError (иначе потребитель упадёт на levels[0])."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    levels = [
        LevelInfo(
            id=rec["id"],
            name=rec["name"],
            params=EngineParams(strength=rec["strength"], timeout_turn_ms=rec["timeout_turn_ms"]),
        )
        for rec in data.get("levels", [])
    ]
    if not levels:
        raise ValueError(f"no levels defined in {path}")
    return levels


def resolve_level(levels: list[LevelInfo], level_id: str) -> LevelInfo | None:
    """LevelInfo по id, или None если нет такого уровня."""
    for lv in levels:
        if lv.id == level_id:
            return lv
    return None
