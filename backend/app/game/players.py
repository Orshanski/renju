from collections.abc import Sequence
from typing import Protocol

from app.domain.values import Point
from app.game.controllers import Controller, User
from app.game_service import engine_move


class Player(Protocol):
    async def take_turn(self, moves: Sequence[Point]) -> Point | None: ...


class InteractivePlayer:
    def __init__(self, user_id: int):
        self.user_id = user_id

    async def take_turn(self, moves: Sequence[Point]) -> Point | None:
        return None  # ход придёт подачей


class EnginePlayer:
    def __init__(self, adapter, params):
        self._adapter = adapter
        self._params = params

    async def take_turn(self, moves: Sequence[Point]) -> Point | None:
        return await engine_move(self._adapter, moves, self._params)


def make_player(ctl: Controller, adapter, levels: dict) -> Player:
    if isinstance(ctl, User):
        return InteractivePlayer(ctl.user_id)
    return EnginePlayer(adapter, levels[ctl.level_id])  # levels: level_id → EngineParams
