"""Фоновый advance партии с дедупом по game_id. Владеет своим стейтом
(набор активных game_id + ссылки на таски), а не размазывает по app.state.

runner(game_id) — корутина, прогоняющая advance в СВОЕЙ сессии. Конкретный runner
(с sessionmaker/service и гейтом adapter-is-None) собирает app_factory."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger("renju.advance")


class AdvanceManager:
    def __init__(self, runner: Callable[[str], Awaitable[None]]):
        self._runner = runner
        self._active: set[str] = set()  # game_id с активным прогоном (дедуп)
        self._tasks: set[asyncio.Task] = set()  # ссылки, чтобы GC не оборвал

    def schedule(self, game_id: str) -> None:
        # Синхронен: между вызовом и снятием cursor в state_payload нет await → cursor
        # снимается ДО первого хода advance (спека §4.6: реплей с этого cursor догонит события).
        if game_id in self._active:  # уже крутится — не плодим дубль
            return
        self._active.add(game_id)
        task = asyncio.create_task(self._run(game_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, game_id: str) -> None:
        try:
            await self._runner(game_id)
        except Exception:
            logger.exception("background advance failed: game=%s", game_id)
        finally:
            self._active.discard(game_id)

    async def drain(self) -> None:
        """Дождаться ЕСТЕСТВЕННОГО завершения активных прогонов (для тестов)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """Shutdown: ОТМЕНИТЬ незавершённые прогоны и дождаться сворачивания.
        Сохраняет семантику прежнего lifespan (app_factory.py:72-75: t.cancel()
        для каждой bg-задачи, затем gather) — НЕ ждём естественного завершения."""
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
