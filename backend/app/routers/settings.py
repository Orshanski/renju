# backend/app/routers/settings.py
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, bump_token_epoch, hash_password, verify_password
from ..db.deps import get_session
from ..exceptions import BadInputError
from ..game.settings_repository import SqlSettingsRepository
from ..models.user import User
from ..models.user_settings import UserSettings
from .auth import current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsDTO(BaseModel):
    games_limit: int
    games_limit_enabled: bool
    undo_enabled: bool
    undo_limit: int | None
    undo_after_game_end: bool


class SettingsBody(BaseModel):
    games_limit: int = Field(ge=10, le=100)
    games_limit_enabled: bool
    undo_enabled: bool
    undo_limit: int | None = Field(default=None, ge=1, le=999)
    undo_after_game_end: bool


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=72)
    new_password: str = Field(min_length=6, max_length=72)


def _to_dto(s: UserSettings) -> SettingsDTO:
    return SettingsDTO(
        games_limit=s.games_limit,
        games_limit_enabled=s.games_limit_enabled,
        undo_enabled=s.undo_enabled,
        undo_limit=s.undo_limit,
        undo_after_game_end=s.undo_after_game_end,
    )


@router.get("", response_model=SettingsDTO)
async def get_settings(
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    repo = SqlSettingsRepository(session)
    return _to_dto(await repo.get_or_default(user.user_id))


@router.put("", response_model=SettingsDTO)
async def put_settings(
    body: SettingsBody,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from ..game.deps import build_game_service

    repo = SqlSettingsRepository(session)
    settings = UserSettings(
        user_id=user.user_id,
        games_limit=body.games_limit,
        games_limit_enabled=body.games_limit_enabled,
        undo_enabled=body.undo_enabled,
        undo_limit=body.undo_limit,
        undo_after_game_end=body.undo_after_game_end,
    )
    await repo.upsert(settings)
    svc = build_game_service(request, session)
    await svc.enforce_limits(user.user_id)
    return _to_dto(await repo.get_or_default(user.user_id))


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordBody,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    db_user = await session.get(User, user.user_id)
    if db_user is None or not verify_password(body.current_password, db_user.password_hash):
        raise BadInputError("Неверный текущий пароль")
    db_user.password_hash = hash_password(body.new_password)
    await session.flush()
    new_epoch = await bump_token_epoch(session, user.user_id)
    await session.commit()
    if new_epoch is None:
        return  # guard: строка не найдена (теоретически невозможно)
    # Обновить epoch в cookie через rolling refresh (middleware/refresh.py)
    request.state.refresh = {"user_id": user.user_id, "role": user.role, "epoch": new_epoch}
