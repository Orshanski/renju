from app.auth import bump_token_epoch, fetch_token_epoch
from app.dal import users as dal


async def test_create_and_get(session):
    uid = await dal.create_user(session, "alice", "pw", role="admin")
    await session.commit()
    u = await dal.get_user_by_username(session, "alice")
    assert u is not None
    assert u.id == uid and u.role == "admin" and u.password_hash != "pw"


async def test_is_last_admin(session):
    a = await dal.create_user(session, "a", "pw", role="admin")
    await session.commit()
    assert await dal.is_last_admin(session, a) is True
    await dal.create_user(session, "b", "pw", role="admin")
    await session.commit()
    assert await dal.is_last_admin(session, a) is False


async def test_bump_epoch(session):
    uid = await dal.create_user(session, "alice", "pw")
    await session.commit()
    assert await fetch_token_epoch(session, uid) == 0
    assert await bump_token_epoch(session, uid) == 1
    await session.commit()
    assert await fetch_token_epoch(session, uid) == 1
    assert await bump_token_epoch(session, 999) is None  # нет строки
