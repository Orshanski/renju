from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user_settings import (
    DEFAULT_CURRENT_LIMIT,
    DEFAULT_FINISHED_LIMIT,
    UserSettings,
)


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
        # Транзиентный объект с явными дефолтами из констант — не персистим,
        # атрибуты доступны сразу без flush/БД.
        return UserSettings(
            user_id=user_id,
            current_limit=DEFAULT_CURRENT_LIMIT,
            current_limit_enabled=True,
            finished_limit=DEFAULT_FINISHED_LIMIT,
            finished_limit_enabled=True,
        )

    async def upsert(self, settings: UserSettings) -> None:
        await self._s.merge(settings)
        await self._s.commit()


class InMemorySettingsRepository:
    def __init__(self):
        self._d: dict[int, UserSettings] = {}

    async def get_or_default(self, user_id: int) -> UserSettings:
        return self._d.get(
            user_id,
            UserSettings(
                user_id=user_id,
                current_limit=DEFAULT_CURRENT_LIMIT,
                current_limit_enabled=True,
                finished_limit=DEFAULT_FINISHED_LIMIT,
                finished_limit_enabled=True,
            ),
        )

    async def upsert(self, settings: UserSettings) -> None:
        self._d[settings.user_id] = settings
