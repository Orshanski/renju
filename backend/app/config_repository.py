"""DAL для конфигурации движка: уровни сложности и глобальные настройки."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import UnknownLevelError
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

    async def _set_nnue(self, nnue: bool) -> None:
        """Записать глобальный nnue. Если строки (id=1) нет — создать: иначе PUT молча
        вернул бы 200, не сохранив nnue (строку сеют миграция/фикстура, но не полагаемся)."""
        settings = await self._s.get(EngineSettings, 1)
        if settings is None:
            self._s.add(EngineSettings(id=1, nnue=nnue))
        else:
            settings.nnue = nnue

    async def update(self, level_updates: list, nnue: bool) -> None:
        """Обновить присланные уровни и глобальный nnue в одной транзакции.

        Если хотя бы один level_id не существует — поднять UnknownLevelError ДО любых
        мутаций (атомарность: ничего не записано). Коммит — на вызывающей стороне.
        Пустой level_updates допустим — тогда меняется только nnue.
        """
        # Проверить существование всех присланных id ДО любых мутаций
        requested_ids = [lu.id for lu in level_updates]
        if requested_ids:
            stmt = select(Level).where(Level.id.in_(requested_ids))
            rows = list((await self._s.execute(stmt)).scalars())
        else:
            rows = []
        found_ids = {row.id for row in rows}
        unknown = [lid for lid in requested_ids if lid not in found_ids]
        if unknown:
            raise UnknownLevelError(unknown)

        # Мутируем загруженные строки (identity map) + глобальный nnue
        level_map = {row.id: row for row in rows}
        for lu in level_updates:
            level = level_map[lu.id]
            level.strength = lu.strength
            level.timeout_ms = lu.timeout_ms
            level.max_depth = lu.max_depth

        await self._set_nnue(nnue)
