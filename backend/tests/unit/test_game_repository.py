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


async def test_sql_crud(session):
    # users-строка нужна под FK; берём реальный id (не полагаемся на autoincrement=1)
    from app.dal import users as udal

    uid = await udal.create_user(session, "alice", "pw")
    await session.commit()
    repo = SqlGameRepository(session)
    await repo.create(_game(owner=uid))
    got = await repo.get("g1")
    assert got is not None
    assert got.id == "g1" and got.moves == [[7, 7]]
    got.status = "finished_draw"
    await repo.update(got)
    updated = await repo.get("g1")
    assert updated is not None and updated.status == "finished_draw"
