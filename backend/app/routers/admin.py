from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, require_admin
from ..config_repository import ConfigRepository, UnknownLevelError
from ..db.deps import get_session
from ..dtos.auth import UserDTO
from ..dtos.engine_config import EngineConfigBody, EngineConfigDTO, LevelConfigDTO
from ..services import admin_service
from .auth import current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def admin_user(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    return require_admin(user)


class CreateUserBody(BaseModel):
    username: str
    password: str = Field(min_length=1, max_length=72)
    role: Literal["admin", "user"] = "user"


class ResetPasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=72)


@router.get("/users", response_model=list[UserDTO])
async def list_users(
    _: Annotated[CurrentUser, Depends(admin_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await admin_service.list_users(session)


@router.post("/users")
async def create_user(
    body: CreateUserBody,
    _: Annotated[CurrentUser, Depends(admin_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    uid = await admin_service.create_user(session, body.username, body.password, body.role)
    return {"id": uid}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    actor: Annotated[CurrentUser, Depends(admin_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await admin_service.delete_user(session, user_id, actor.user_id)
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    body: ResetPasswordBody,
    _: Annotated[CurrentUser, Depends(admin_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await admin_service.reset_password(session, user_id, body.password)
    return {"ok": True}


def _build_engine_config_dto(levels: list, nnue: bool) -> EngineConfigDTO:
    return EngineConfigDTO(
        levels=[
            LevelConfigDTO(id=lv.id, name=lv.name, strength=lv.strength, timeout_ms=lv.timeout_ms)
            for lv in levels
        ],
        nnue=nnue,
    )


@router.get("/engine-config", response_model=EngineConfigDTO)
async def get_engine_config(
    _: Annotated[CurrentUser, Depends(admin_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EngineConfigDTO:
    repo = ConfigRepository(session)
    levels = await repo.levels()
    return _build_engine_config_dto(levels, await repo.nnue())


@router.put("/engine-config", response_model=EngineConfigDTO)
async def put_engine_config(
    body: EngineConfigBody,
    _: Annotated[CurrentUser, Depends(admin_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EngineConfigDTO:
    repo = ConfigRepository(session)
    try:
        await repo.update(body.levels, body.nnue)
    except UnknownLevelError as exc:
        raise HTTPException(
            status_code=422, detail=f"Unknown level ids: {exc.unknown_ids}"
        ) from exc
    await session.commit()
    levels = await repo.levels()
    return _build_engine_config_dto(levels, await repo.nnue())
