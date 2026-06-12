from sqlalchemy import text


async def test_pragmas_applied(session):
    assert (await session.execute(text("PRAGMA foreign_keys"))).scalar() == 1
    assert (await session.execute(text("PRAGMA journal_mode"))).scalar().lower() == "wal"


async def test_make_engine_creates_missing_data_dir(tmp_path, monkeypatch):
    # свежий деплой: data_dir ещё не существует → make_engine должен его создать,
    # иначе sqlite падает с «unable to open database file» (поймали smoke 2026-06-12)
    from app.config import Settings
    from app.db.engine import make_engine

    target = tmp_path / "fresh" / "data"
    monkeypatch.setenv("RENJU_DATA_DIR", str(target))
    assert not target.exists()
    eng = make_engine(Settings())
    try:
        assert target.exists()  # каталог создан до открытия файла БД
    finally:
        await eng.dispose()
