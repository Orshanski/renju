from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.config import Settings
from app.db.deps import get_session, get_settings
from app.dtos.auth import LoginRequest, LoginResponse, UserDTO
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )


def _set_cookie(response: Response, token: str, s: Settings) -> None:
    response.set_cookie(
        s.cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=s.secure_cookie,
        max_age=s.jwt_expire_hours * 3600,
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    token, user = await auth_service.login(
        session, body.username, body.password, _client_ip(request), settings
    )
    _set_cookie(response, token, settings)
    return LoginResponse(user=user)


async def current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    return await get_current_user(request, session, settings)


@router.get("/me", response_model=UserDTO)
async def me(
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await auth_service.get_me(session, user.user_id)


@router.post("/logout")
async def logout(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
):
    response.delete_cookie(
        settings.cookie_name,
        path="/",
        samesite="lax",
        secure=settings.secure_cookie,
    )  # epoch не трогаем
    return {"ok": True}
