import time

from ..auth import AuthError, create_token, verify_password
from ..dal import users as dal
from ..dtos.auth import UserDTO
from ..exceptions import RateLimitError

_MAX_ATTEMPTS = 5
_WINDOW_SEC = 300
_MAX_TRACKED_IPS = 10_000
_attempts: dict[str, list[float]] = {}  # секции синхронны (без await) → атомарны в loop


def reset_rate_limit() -> None:
    _attempts.clear()


def _purge(now: float) -> None:
    for ip in [ip for ip, ts in _attempts.items() if all(now - t >= _WINDOW_SEC for t in ts)]:
        del _attempts[ip]


def _allowed(ip: str, now: float) -> bool:
    if len(_attempts) > _MAX_TRACKED_IPS:
        _purge(now)
    fresh = [t for t in _attempts.get(ip, []) if now - t < _WINDOW_SEC]
    if fresh:
        _attempts[ip] = fresh
    else:
        _attempts.pop(ip, None)
    return len(fresh) < _MAX_ATTEMPTS


async def login(session, username: str, password: str, ip: str, settings) -> tuple[str, UserDTO]:
    now = time.monotonic()
    if not _allowed(ip, now):
        raise RateLimitError("Too many login attempts")
    user = await dal.get_user_by_username(session, username)
    if user is None or not verify_password(password, user.password_hash):
        _attempts.setdefault(ip, []).append(now)
        raise AuthError("Invalid credentials")
    _attempts.pop(ip, None)
    token = create_token(user.id, user.role, user.token_epoch, settings)
    return token, UserDTO(id=user.id, username=user.username, role=user.role)


async def get_me(session, user_id: int) -> UserDTO:
    from ..exceptions import NotFoundError

    user = await dal.get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return UserDTO(id=user.id, username=user.username, role=user.role)
