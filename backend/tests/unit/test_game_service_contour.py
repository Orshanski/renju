from app.game.event_hub import InMemoryEventHub
from app.game.repository import InMemoryGameRepository
from app.game.service import GameService


class FakeAdapter:
    def __init__(self):
        self.forbid = [(3, 3)]
        self.move = (8, 8)

    async def forbidden_points(self, moves):
        return list(self.forbid)

    async def compute_move(self, moves, params, allowed_zone=None):
        return self.move


def _svc(adapter=None):
    return GameService(
        repo=InMemoryGameRepository(),
        hub=InMemoryEventHub(),
        adapter=adapter or FakeAdapter(),
        levels={"master": object()},
    )


async def test_fouls_memoized_one_engine_call():
    svc = _svc()
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points

    async def counting(moves):
        svc._adapter.calls += 1
        return await orig(moves)

    svc._adapter.forbidden_points = counting
    from app.models.game import Game

    g = Game(
        id="g",
        owner_id=1,
        controllers={},
        moves=[[7, 7], [8, 8]],
        status="awaiting_move",
        undo_count=0,
        forbidden_log={},
    )
    f1 = await svc.fouls(g, g.moves)  # len 2 (чёрные) → движок, запись
    f2 = await svc.fouls(g, g.moves)  # из лога
    assert f1 == [(3, 3)] and f2 == [(3, 3)] and svc._adapter.calls == 1
    assert g.forbidden_log["2"] == [[3, 3]]


async def test_fouls_white_to_move_empty_no_engine():
    svc = _svc()
    svc._adapter.calls = 0
    from app.models.game import Game

    g = Game(
        id="g",
        owner_id=1,
        controllers={},
        moves=[[7, 7]],
        status="awaiting_move",
        undo_count=0,
        forbidden_log={},
    )
    assert await svc.fouls(g, g.moves) == []  # len 1 (белые) → []
