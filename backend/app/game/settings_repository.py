from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user_settings import DEFAULT_GAMES_LIMIT, UserSettings


class SettingsRepository(Protocol):
    async def get_or_default(self, user_id: int) -> UserSettings: ...
    async def upsert(self, settings: UserSettings) -> None: ...


class SqlSettingsRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def get_or_default(self, user_id: int) -> UserSettings:
        obj = await self._s.get(UserSettings, user_id)
        if obj is not None:
            return obj
        return UserSettings(
            user_id=user_id,
            games_limit=DEFAULT_GAMES_LIMIT,
            games_limit_enabled=True,
            undo_enabled=True,
            undo_limit=None,
            undo_after_game_end=True,
        )

    async def upsert(self, settings: UserSettings) -> None:
        await self._s.merge(settings)
        await self._s.commit()


class InMemorySettingsRepository:
    def __init__(self):
        self._d: dict[int, UserSettings] = {}

    async def get_or_default(self, user_id: int) -> UserSettings:
        if user_id in self._d:
            return self._d[user_id]
        return UserSettings(
            user_id=user_id,
            games_limit=DEFAULT_GAMES_LIMIT,
            games_limit_enabled=True,
            undo_enabled=True,
            undo_limit=None,
            undo_after_game_end=True,
        )

    async def upsert(self, settings: UserSettings) -> None:
        self._d[settings.user_id] = settings
