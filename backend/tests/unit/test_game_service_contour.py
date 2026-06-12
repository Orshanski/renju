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


async def test_create_hve_human_black_pending_engine():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    # центр (ход 1 = чёрные) предзаполнен = ход человека; ход 2 за движком-белым → ждём фон
    assert g.moves == [[7, 7]] and g.status == "opponent_thinking"


async def test_create_hve_human_white_awaits_human():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="white")
    # центр = ход 1 = чёрные = движок (предзаполнен); ход 2 за человеком-белым
    assert g.moves == [[7, 7]] and g.status == "awaiting_move"


async def test_advance_drives_engine_move():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    await svc.advance(g)  # «фон»: движок-белый ходит 2-м
    assert g.moves == [[7, 7], [8, 8]] and g.status == "awaiting_move"


async def test_neutrality_both_interactive_pvp_no_autoplay():
    svc = _svc()
    from app.models.game import Game

    g = Game(
        id="g",
        owner_id=1,
        moves=[[7, 7]],
        undo_count=0,
        forbidden_log={},
        controllers={
            "black": {"kind": "user", "user_id": 1},
            "white": {"kind": "user", "user_id": 2},
        },
        status="awaiting_move",
    )
    await svc._repo.create(g)
    await svc.advance(g)
    assert g.moves == [[7, 7]] and g.status == "awaiting_move"  # advance НЕ ходит сам


async def test_advance_engine_error_publishes_error_event():
    from app.rapfi.adapter import EngineError

    svc = _svc()

    async def boom(moves, params, allowed_zone=None):
        raise EngineError("twice")

    svc._adapter.compute_move = boom
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    assert g.status == "opponent_thinking"
    await svc.advance(g)  # движок падает → error-событие, статус НЕ меняется (§4.8 доиграет позже)
    assert g.status == "opponent_thinking"
    assert any(e["type"] == "error" for e in svc._hub._log.get(g.id, []))
