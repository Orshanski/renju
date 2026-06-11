import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from fastapi import Request
from sqlalchemy import select, update

from app.config import Settings
from app.exceptions import ForbiddenError

log = logging.getLogger("renju.auth")
_INVALID = "Invalid token"
# ЗАПРЕТ module-level Settings(): модуль импортируется ОДИН раз → frozen Settings
# проигнорирует monkeypatch.setenv в тестах. Settings приходит ПАРАМЕТРОМ (из
# app.state.settings в роутерах/мидлварах; напрямую в юнит-тестах).


class AuthError(Exception):
    """Нет/невалидный токен или креды. → 401."""


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int, role: str, token_epoch: int, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "userId": user_id,
        "role": role,
        "tep": token_epoch,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.resolved_secret_key(), algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    return jwt.decode(token, settings.resolved_secret_key(), algorithms=[settings.jwt_algorithm])


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    role: str

    @classmethod
    def from_payload(cls, p: dict[str, Any]) -> "CurrentUser":
        uid = p.get("userId")
        # bool — подкласс int; без этой проверки True прошёл бы как int
        if isinstance(uid, bool) or not isinstance(uid, int):
            log.warning("JWT malformed: userId")
            raise AuthError(_INVALID)
        role = p.get("role")
        if not isinstance(role, str) or not role:
            log.warning("JWT malformed: role")
            raise AuthError(_INVALID)
        return cls(user_id=uid, role=role)


async def fetch_token_epoch(session, user_id: int) -> int | None:
    from app.models.user import User

    return await session.scalar(select(User.token_epoch).where(User.id == user_id))


async def bump_token_epoch(session, user_id: int) -> int | None:
    """UPDATE … RETURNING; новый epoch или None если строки нет (guard на гонку reset×delete)."""
    from app.models.user import User

    return await session.scalar(
        update(User)
        .where(User.id == user_id)
        .values(token_epoch=User.token_epoch + 1)
        .returning(User.token_epoch)
    )


def token_needs_refresh(payload: dict, settings: Settings) -> bool:
    iat = payload.get("iat")
    if not iat:
        return False
    # iat кладётся как datetime, PyJWT декодирует как unix-timestamp
    issued = datetime.fromtimestamp(iat, tz=UTC)
    return datetime.now(UTC) - issued > timedelta(hours=settings.jwt_refresh_after_hours)


async def get_current_user(request: Request, session, settings: Settings) -> CurrentUser:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise AuthError("Not authenticated")
    try:
        payload = decode_token(token, settings)
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired") from None
    except jwt.InvalidTokenError:
        raise AuthError(_INVALID) from None
    user = CurrentUser.from_payload(payload)
    # token_epoch — прямо из БД (без кеша); §4.4
    db_epoch = await fetch_token_epoch(session, user.user_id)
    if db_epoch is None or payload.get("tep", 0) != db_epoch:
        raise AuthError(_INVALID)
    if token_needs_refresh(payload, settings):
        request.state.refresh = {"user_id": user.user_id, "role": user.role, "epoch": db_epoch}
    return user


def require_admin(user: CurrentUser) -> CurrentUser:
    if user.role != "admin":
        raise ForbiddenError("Admin access required")
    return user
