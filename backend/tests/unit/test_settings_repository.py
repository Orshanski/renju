from app.game.settings_repository import InMemorySettingsRepository, SqlSettingsRepository
from app.models.user_settings import DEFAULT_GAMES_LIMIT, UserSettings


async def test_inmemory_get_or_default_returns_defaults():
    r = InMemorySettingsRepository()
    s = await r.get_or_default(42)
    assert s.games_limit == DEFAULT_GAMES_LIMIT
    assert s.games_limit_enabled is True
    assert s.undo_enabled is True
    assert s.undo_limit is None
    assert s.undo_after_game_end is True


async def test_inmemory_upsert_and_get():
    r = InMemorySettingsRepository()
    settings = UserSettings(
        user_id=7,
        games_limit=20,
        games_limit_enabled=False,
        undo_enabled=False,
        undo_limit=3,
        undo_after_game_end=False,
    )
    await r.upsert(settings)
    got = await r.get_or_default(7)
    assert got.games_limit == 20
    assert got.games_limit_enabled is False
    assert got.undo_enabled is False
    assert got.undo_limit == 3
    assert got.undo_after_game_end is False


async def test_inmemory_upsert_overwrites():
    r = InMemorySettingsRepository()
    s1 = UserSettings(
        user_id=3,
        games_limit=10,
        games_limit_enabled=True,
        undo_enabled=True,
        undo_limit=None,
        undo_after_game_end=True,
    )
    await r.upsert(s1)
    s2 = UserSettings(
        user_id=3,
        games_limit=100,
        games_limit_enabled=False,
        undo_enabled=False,
        undo_limit=5,
        undo_after_game_end=False,
    )
    await r.upsert(s2)
    got = await r.get_or_default(3)
    assert got.games_limit == 100
    assert got.games_limit_enabled is False
    assert got.undo_limit == 5


async def test_sql_get_or_default_no_row(session):
    from app.dal import users as udal

    uid = await udal.create_user(session, "bob_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    s = await r.get_or_default(uid)
    assert s.games_limit == DEFAULT_GAMES_LIMIT
    assert s.games_limit_enabled is True
    assert s.undo_enabled is True
    assert s.undo_limit is None
    assert s.undo_after_game_end is True


async def test_sql_upsert_and_get(session, engine):
    from app.dal import users as udal
    from app.db.session import make_sessionmaker

    uid = await udal.create_user(session, "carol_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    settings = UserSettings(
        user_id=uid,
        games_limit=30,
        games_limit_enabled=True,
        undo_enabled=True,
        undo_limit=10,
        undo_after_game_end=False,
    )
    await r.upsert(settings)
    async with make_sessionmaker(engine)() as s2:
        got = await SqlSettingsRepository(s2).get_or_default(uid)
    assert got.games_limit == 30
    assert got.undo_limit == 10
    assert got.undo_after_game_end is False


async def test_sql_upsert_overwrites(session, engine):
    from app.dal import users as udal
    from app.db.session import make_sessionmaker

    uid = await udal.create_user(session, "dave_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    s1 = UserSettings(
        user_id=uid,
        games_limit=50,
        games_limit_enabled=True,
        undo_enabled=True,
        undo_limit=None,
        undo_after_game_end=True,
    )
    await r.upsert(s1)
    s2 = UserSettings(
        user_id=uid,
        games_limit=20,
        games_limit_enabled=False,
        undo_enabled=False,
        undo_limit=2,
        undo_after_game_end=False,
    )
    await r.upsert(s2)
    async with make_sessionmaker(engine)() as s3:
        got = await SqlSettingsRepository(s3).get_or_default(uid)
    assert got.games_limit == 20
    assert got.games_limit_enabled is False
    assert got.undo_limit == 2
