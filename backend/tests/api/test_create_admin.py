async def test_create_admin_inserts(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    import app.models.user  # noqa: F401
    from app.config import Settings
    from app.db.base import Base
    from app.db.engine import make_engine

    eng = make_engine(Settings())
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()

    from scripts.create_admin import create_admin

    await create_admin("root", "pw")

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.dal import users as dal

    eng2 = create_async_engine(f"sqlite+aiosqlite:///{Settings().resolved_db_path}")
    async with AsyncSession(eng2) as s:
        u = await dal.get_user_by_username(s, "root")
        assert u is not None and u.role == "admin"
    await eng2.dispose()
