from collections.abc import Sequence
from typing import Protocol

from ..domain.engine_params import EngineParams
from ..domain.values import Point
from .controllers import Controller, Engine, User
from .moves import engine_move
from .ports import EngineAdapter


class Player(Protocol):
    async def take_turn(self, moves: Sequence[Point]) -> Point | None: ...


class InteractivePlayer:
    def __init__(self, user_id: int):
        self.user_id = user_id

    async def take_turn(self, moves: Sequence[Point]) -> Point | None:
        return None  # ход придёт подачей


class EnginePlayer:
    def __init__(
        self, adapter: EngineAdapter, params: EngineParams, game_id: str, level_tag: str = "-"
    ):
        self._adapter = adapter
        self._params = params
        self._game_id = game_id
        self._level_tag = level_tag

    async def take_turn(self, moves: Sequence[Point]) -> Point | None:
        return await engine_move(self._adapter, moves, self._params, self._game_id, self._level_tag)


def make_player(ctl: Controller, adapter: EngineAdapter, game_id: str) -> Player:
    if isinstance(ctl, User):
        return InteractivePlayer(ctl.user_id)  # game_id игнорируется (ход придёт подачей)
    assert isinstance(ctl, Engine)
    # Параметры берём из замороженного снимка контроллера, не из глобального словаря уровней
    params = EngineParams(strength=ctl.strength, timeout_turn_ms=ctl.timeout_ms)
    return EnginePlayer(adapter, params, game_id, level_tag=ctl.level_id)
