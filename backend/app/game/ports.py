"""Порты игрового слоя: что игровой слой ТРЕБУЕТ от инфраструктуры (§4.9).

Контракты объявлены на стороне потребителя (игровой слой); реализуют их
EngineRegistry (адаптер движка) и InMemoryEventHub (шина). Делает их подменяемыми
и убирает утиную типизацию (getattr) в сервисе. Сигнатуры зеркалят registry.py."""

from collections.abc import AsyncGenerator, Sequence
from typing import Protocol

from ..domain.engine_params import EngineParams
from ..domain.values import Point


class EngineAdapter(Protocol):
    async def compute_move(
        self,
        game_id: str,
        moves: Sequence[Point],
        params: EngineParams,
        allowed_zone: frozenset[Point] | None = None,
        *,
        level_tag: str = "-",
        nnue: bool | None = None,
    ) -> Point: ...

    async def forbidden_points(
        self,
        game_id: str,
        moves: Sequence[Point],
        *,
        level_tag: str = "-",
        nnue: bool | None = None,
    ) -> list[Point]: ...

    async def sync_after_undo(
        self, game_id: str, moves: Sequence[Point], *, level_tag: str = "-"
    ) -> None: ...


class EventHub(Protocol):
    def publish(self, game_id: str, type_: str, payload: dict) -> int: ...
    def cursor(self, game_id: str) -> int: ...
    def subscribe(
        self, game_id: str, since: int, idle_timeout: float | None = None
    ) -> AsyncGenerator[dict]: ...
