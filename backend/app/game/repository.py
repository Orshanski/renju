from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Game


class GameRepository(Protocol):
    async def create(self, game: Game) -> None: ...
    async def get(self, game_id: str) -> Game | None: ...
    async def list_by_owner(self, owner_id: int) -> list[Game]: ...
    async def update(self, game: Game) -> None: ...


class SqlGameRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def create(self, game: Game) -> None:
        self._s.add(game)
        await self._s.commit()  # писатель коммитит явно (срез 1)

    async def get(self, game_id: str) -> Game | None:
        return await self._s.get(Game, game_id)

    async def list_by_owner(self, owner_id: int) -> list[Game]:
        return list(
            (
                await self._s.execute(
                    select(Game).where(Game.owner_id == owner_id).order_by(Game.created_at)
                )
            ).scalars()
        )

    async def update(self, game: Game) -> None:
        await self._s.commit()  # game уже tracked сессией; коммитим изменения


class InMemoryGameRepository:
    def __init__(self):
        self._d: dict[str, Game] = {}

    async def create(self, game: Game) -> None:
        self._d[game.id] = game

    async def get(self, game_id: str) -> Game | None:
        return self._d.get(game_id)

    async def list_by_owner(self, owner_id: int) -> list[Game]:
        return [g for g in self._d.values() if g.owner_id == owner_id]

    async def update(self, game: Game) -> None:
        self._d[game.id] = game
