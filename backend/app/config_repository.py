"""DAL для конфигурации движка: уровни сложности и глобальные настройки."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models.level import EngineSettings, Level


class ConfigRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def levels(self) -> list[Level]:
        return list((await self._s.execute(select(Level).order_by(Level.ordering))).scalars())

    async def get_level(self, level_id: str) -> Level | None:
        return await self._s.get(Level, level_id)

    async def nnue(self) -> bool:
        s = await self._s.get(EngineSettings, 1)
        return bool(s.nnue) if s is not None else True
