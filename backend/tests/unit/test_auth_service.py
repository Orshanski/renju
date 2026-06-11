import pytest

from app.auth import AuthError, decode_token
from app.config import Settings
from app.dal import users as dal
from app.exceptions import RateLimitError
from app.services import auth_service

# env с tmp data_dir активен в теле теста через фикстуру session (engine → monkeypatch)


async def test_login_ok(session):
    await dal.create_user(session, "alice", "pw", role="admin")
    await session.commit()
    auth_service.reset_rate_limit()
    cfg = Settings()
    token, user = await auth_service.login(session, "alice", "pw", ip="1.1.1.1", settings=cfg)
    assert user.username == "alice" and user.role == "admin"
    assert decode_token(token, cfg)["userId"] == user.id


async def test_login_bad_password(session):
    await dal.create_user(session, "alice", "pw")
    await session.commit()
    auth_service.reset_rate_limit()
    with pytest.raises(AuthError):
        await auth_service.login(session, "alice", "WRONG", ip="2.2.2.2", settings=Settings())


async def test_rate_limit_after_5(session):
    auth_service.reset_rate_limit()
    for _ in range(5):
        with pytest.raises(AuthError):
            await auth_service.login(session, "ghost", "x", ip="3.3.3.3", settings=Settings())
    with pytest.raises(RateLimitError):
        await auth_service.login(session, "ghost", "x", ip="3.3.3.3", settings=Settings())
