from sqlalchemy import text


async def test_pragmas_applied(session):
    assert (await session.execute(text("PRAGMA foreign_keys"))).scalar() == 1
    assert (await session.execute(text("PRAGMA journal_mode"))).scalar().lower() == "wal"
