import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import Settings

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
