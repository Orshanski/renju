from typing import Annotated

from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.deps import get_session
from .repository import SqlGameRepository
from .service import GameService
from .settings_repository import SqlSettingsRepository


def make_game_service(app: FastAPI, session: AsyncSession) -> GameService:
    """Сборка GameService на ЯВНОЙ сессии (переиспользуется в DI и в SSE-стриме,
    который держит свою короткую сессию). Перенос тела games.py:30-38."""
    levels = {lid: lv.params for lid, lv in app.state.levels.items()}
    return GameService(
        repo=SqlGameRepository(session),
        hub=app.state.event_hub,
        adapter=app.state.adapter,
        levels=levels,
        settings_repo=SqlSettingsRepository(session),
    )


def build_game_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GameService:
    """FastAPI-зависимость: тонкая обёртка над make_game_service на request-сессии."""
    return make_game_service(request.app, session)
