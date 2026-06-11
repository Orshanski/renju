"""Параметры движка Rapfi для одного уровня. Чистый тип, без I/O."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineParams:
    strength: int  # INFO strength, 0..100 (100 — без человеческого ослабления)
    timeout_turn_ms: int  # INFO timeout_turn
