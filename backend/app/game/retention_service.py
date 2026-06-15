"""Вытеснение партий по лимитам (ретеншн). Выделено из GameService."""

from datetime import datetime

from ..domain.retention import Evictable, Section, game_section, select_evictions
from ._time import _now
from .repository import GameRepository
from .settings_repository import SettingsRepository


class RetentionService:
    def __init__(self, repo: GameRepository, settings_repo: SettingsRepository):
        self._repo = repo
        self._settings_repo = settings_repo

    async def evict_current(self, owner_id: int) -> None:
        """Подрезает раздел CURRENT для владельца до current_limit."""
        settings = await self._settings_repo.get_or_default(owner_id)
        if not settings.current_limit_enabled:
            return
        games = await self._repo.list_by_owner(owner_id)
        candidates: list[Evictable] = []
        for g in games:
            if game_section(g.status, bool(g.favorite)) is not Section.CURRENT:
                continue
            # updated_at — sort_key для текущих; created_at — тай-брейк
            # В InMemory-репо updated_at может быть None (БД не заполняет автоматически).
            # Fallback: created_at (консервативно — не падаем на None в сортировке).
            sort_key: datetime = (
                g.updated_at if g.updated_at is not None else (g.created_at or _now())
            )
            created_at: datetime = g.created_at if g.created_at is not None else _now()
            candidates.append(Evictable(id=g.id, sort_key=sort_key, created_at=created_at))
        for game_id in select_evictions(candidates, settings.current_limit):
            await self._repo.delete(game_id)

    async def evict_finished(self, owner_id: int) -> None:
        """Подрезает раздел FINISHED для владельца до finished_limit."""
        settings = await self._settings_repo.get_or_default(owner_id)
        if not settings.finished_limit_enabled:
            return
        games = await self._repo.list_by_owner(owner_id)
        candidates: list[Evictable] = []
        for g in games:
            if game_section(g.status, bool(g.favorite)) is not Section.FINISHED:
                continue
            # finished_at — sort_key для завершённых; fallback: created_at (легаси/edge, не падаем).
            sort_key = g.finished_at if g.finished_at is not None else (g.created_at or _now())
            created_at: datetime = g.created_at if g.created_at is not None else _now()
            candidates.append(Evictable(id=g.id, sort_key=sort_key, created_at=created_at))
        for game_id in select_evictions(candidates, settings.finished_limit):
            await self._repo.delete(game_id)

    async def enforce_limits(self, owner_id: int) -> None:
        """Подрезает оба раздела (CURRENT + FINISHED) до лимитов.
        Вызывается из settings-update эндпоинта."""
        await self.evict_current(owner_id)
        await self.evict_finished(owner_id)
