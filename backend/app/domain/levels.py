"""Уровни сложности: enum → параметры Rapfi (спек §4.5).

Числа предварительные, калибруются на живой игре. Клиент значений не знает —
получает только id+имя (этап 3, GET /levels).
"""

from dataclasses import dataclass
from enum import StrEnum


class Level(StrEnum):
    NOVICE = "novice"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    MASTER = "master"


@dataclass(frozen=True)
class EngineParams:
    strength: int  # INFO strength, 0..100 (100 — без человеческого ослабления)
    timeout_turn_ms: int  # INFO timeout_turn


LEVELS: dict[Level, EngineParams] = {
    Level.NOVICE: EngineParams(strength=10, timeout_turn_ms=1000),
    Level.EASY: EngineParams(strength=30, timeout_turn_ms=1500),
    Level.MEDIUM: EngineParams(strength=55, timeout_turn_ms=2500),
    Level.HARD: EngineParams(strength=80, timeout_turn_ms=4000),
    Level.MASTER: EngineParams(strength=100, timeout_turn_ms=7000),
}
