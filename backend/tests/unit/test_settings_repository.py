from app.game.settings_repository import InMemorySettingsRepository, SqlSettingsRepository
from app.models.user_settings import (
    DEFAULT_CURRENT_LIMIT,
    DEFAULT_FINISHED_LIMIT,
    UserSettings,
)


async def test_inmemory_get_or_default_returns_defaults():
    r = InMemorySettingsRepository()
    s = await r.get_or_default(42)
    assert s.current_limit == DEFAULT_CURRENT_LIMIT
    assert s.finished_limit == DEFAULT_FINISHED_LIMIT
    assert s.current_limit_enabled is True
    assert s.finished_limit_enabled is True


async def test_inmemory_upsert_and_get():
    r = InMemorySettingsRepository()
    settings = UserSettings(
        user_id=7,
        current_limit=5,
        current_limit_enabled=False,
        finished_limit=20,
        finished_limit_enabled=True,
    )
    await r.upsert(settings)
    got = await r.get_or_default(7)
    assert got.current_limit == 5
    assert got.current_limit_enabled is False
    assert got.finished_limit == 20
    assert got.finished_limit_enabled is True


async def test_inmemory_upsert_overwrites():
    r = InMemorySettingsRepository()
    s1 = UserSettings(
        user_id=3,
        current_limit=10,
        current_limit_enabled=True,
        finished_limit=50,
        finished_limit_enabled=True,
    )
    await r.upsert(s1)
    s2 = UserSettings(
        user_id=3,
        current_limit=99,
        current_limit_enabled=False,
        finished_limit=1,
        finished_limit_enabled=False,
    )
    await r.upsert(s2)
    got = await r.get_or_default(3)
    assert got.current_limit == 99
    assert got.current_limit_enabled is False
    assert got.finished_limit == 1
    assert got.finished_limit_enabled is False


async def test_sql_get_or_default_no_row(session):
    from app.dal import users as udal

    uid = await udal.create_user(session, "bob_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    s = await r.get_or_default(uid)
    assert s.current_limit == DEFAULT_CURRENT_LIMIT
    assert s.finished_limit == DEFAULT_FINISHED_LIMIT
    assert s.current_limit_enabled is True
    assert s.finished_limit_enabled is True


async def test_sql_upsert_and_get(session, engine):
    from app.dal import users as udal
    from app.db.session import make_sessionmaker

    uid = await udal.create_user(session, "carol_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    settings = UserSettings(
        user_id=uid,
        current_limit=3,
        current_limit_enabled=False,
        finished_limit=77,
        finished_limit_enabled=True,
    )
    await r.upsert(settings)
    # durability: читаем свежей сессией
    async with make_sessionmaker(engine)() as s2:
        got = await SqlSettingsRepository(s2).get_or_default(uid)
    assert got.current_limit == 3
    assert got.current_limit_enabled is False
    assert got.finished_limit == 77
    assert got.finished_limit_enabled is True


async def test_sql_upsert_overwrites(session, engine):
    from app.dal import users as udal
    from app.db.session import make_sessionmaker

    uid = await udal.create_user(session, "dave_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    s1 = UserSettings(
        user_id=uid,
        current_limit=10,
        current_limit_enabled=True,
        finished_limit=50,
        finished_limit_enabled=True,
    )
    await r.upsert(s1)
    s2 = UserSettings(
        user_id=uid,
        current_limit=2,
        current_limit_enabled=False,
        finished_limit=5,
        finished_limit_enabled=False,
    )
    await r.upsert(s2)
    async with make_sessionmaker(engine)() as s3:
        got = await SqlSettingsRepository(s3).get_or_default(uid)
    assert got.current_limit == 2
    assert got.current_limit_enabled is False
    assert got.finished_limit == 5
    assert got.finished_limit_enabled is False
