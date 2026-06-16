"""DAL для конфигурации движка: уровни сложности и глобальные настройки."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models.level import EngineSettings, Level


class UnknownLevelError(ValueError):
    """Запрошенный level_id не существует в БД."""

    def __init__(self, unknown_ids: list[str]) -> None:
        self.unknown_ids = unknown_ids
        super().__init__(f"Unknown level ids: {unknown_ids}")


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

    async def update(self, level_updates: list, nnue: bool) -> None:
        """Обновить уровни и глобальный nnue в одной транзакции.

        Если хотя бы один level_id не существует — поднять UnknownLevelError,
        ничего не коммитя (атомарность гарантирована вызывающей стороной через
        HTTPException до любого flush).
        """
        if not level_updates:
            # нет обновлений уровней — только nnue
            settings = await self._s.get(EngineSettings, 1)
            if settings is not None:
                settings.nnue = nnue
            return

        # Проверить, что все присланные id существуют
        requested_ids = [lu.id for lu in level_updates]
        rows = list(
            (await self._s.execute(select(Level).where(Level.id.in_(requested_ids)))).scalars()
        )
        found_ids = {row.id for row in rows}
        unknown = [lid for lid in requested_ids if lid not in found_ids]
        if unknown:
            raise UnknownLevelError(unknown)

        # Обновить уровни (rows уже загружены в identity map — просто мутируем)
        level_map = {row.id: row for row in rows}
        for lu in level_updates:
            level = level_map[lu.id]
            level.strength = lu.strength
            level.timeout_ms = lu.timeout_ms

        # Обновить глобальные настройки
        settings = await self._s.get(EngineSettings, 1)
        if settings is not None:
            settings.nnue = nnue
