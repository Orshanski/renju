from app.game.repository import InMemoryGameRepository, SqlGameRepository
from app.models.game import Game


def _game(gid="g1", owner=1):
    return Game(
        id=gid,
        owner_id=owner,
        controllers={
            "black": {"kind": "user", "user_id": owner},
            "white": {"kind": "engine", "level_id": "master"},
        },
        moves=[[7, 7]],
        status="awaiting_move",
        undo_count=0,
        forbidden_log={},
    )


async def test_inmemory_crud():
    repo = InMemoryGameRepository()
    await repo.create(_game())
    g1 = await repo.get("g1")
    assert g1 is not None and g1.id == "g1"
    assert await repo.get("missing") is None
    assert [g.id for g in await repo.list_by_owner(1)] == ["g1"]


async def test_inmemory_delete():
    repo = InMemoryGameRepository()
    await repo.create(_game())
    await repo.delete("g1")
    assert await repo.get("g1") is None


async def test_inmemory_delete_idempotent():
    repo = InMemoryGameRepository()
    # удаление несуществующей партии не падает
    await repo.delete("nonexistent")


async def test_sql_crud(session, engine):
    # users-строка нужна под FK; берём реальный id (не полагаемся на autoincrement=1)
    from app.dal import users as udal
    from app.db.session import make_sessionmaker

    uid = await udal.create_user(session, "alice", "pw")
    await session.commit()
    repo = SqlGameRepository(session)
    await repo.create(_game(owner=uid))
    got = await repo.get("g1")
    assert got is not None
    assert got.id == "g1" and got.moves == [[7, 7]]
    got.status = "finished_draw"
    await repo.update(got)
    # durability: перечитываем СВЕЖЕЙ сессией (отдельная транзакция видит только
    # закоммиченное) — это ловит дропнутый writer-commit, чего одна сессия с
    # expire_on_commit=False + identity-map/autoflush НЕ поймала бы.
    async with make_sessionmaker(engine)() as s2:
        reread = await SqlGameRepository(s2).get("g1")
    assert reread is not None and reread.status == "finished_draw"


async def test_sql_delete(session, engine):
    from app.dal import users as udal
    from app.db.session import make_sessionmaker

    uid = await udal.create_user(session, "alice_del", "pw")
    await session.commit()
    repo = SqlGameRepository(session)
    await repo.create(_game("gdel", owner=uid))
    await repo.delete("gdel")
    async with make_sessionmaker(engine)() as s2:
        gone = await SqlGameRepository(s2).get("gdel")
    assert gone is None


async def test_sql_delete_idempotent(session):
    from app.dal import users as udal

    await udal.create_user(session, "alice_del2", "pw")
    await session.commit()
    repo = SqlGameRepository(session)
    # удаление несуществующей партии не падает
    await repo.delete("no-such-game")
