from app.game.controllers import Engine, User, controller_from_json, controller_to_json
from app.game.players import EnginePlayer, InteractivePlayer, make_player

_MASTER = Engine(level_id="master", strength=90, timeout_ms=6000, nnue=True)
_NOVICE = Engine(level_id="novice", strength=1, timeout_ms=100, nnue=False)


def test_controller_roundtrip():
    assert controller_from_json(controller_to_json(_MASTER)) == _MASTER
    assert controller_from_json(controller_to_json(User(7))) == User(7)


async def test_interactive_player_take_turn_none():
    p = InteractivePlayer(7)
    assert await p.take_turn([(7, 7)]) is None


async def test_make_player_dispatch():
    from typing import cast
    from app.game.ports import EngineAdapter

    fake_adapter = cast(EngineAdapter, object())
    assert isinstance(make_player(User(7), fake_adapter, "g"), InteractivePlayer)
    assert isinstance(make_player(_MASTER, fake_adapter, "g"), EnginePlayer)


async def test_engine_player_passes_game_id():
    captured = {}

    class FakeReg:
        async def compute_move(
            self, game_id, moves, params, allowed_zone=None, *, level_tag="-", nnue=None
        ):
            captured["game_id"] = game_id
            captured["level_tag"] = level_tag
            return (7, 8)

        async def forbidden_points(self, game_id, moves, *, level_tag="-", nnue=None):
            return []

        async def sync_after_undo(self, game_id, moves, *, level_tag="-"):
            pass

    p = make_player(_NOVICE, FakeReg(), "game-77")
    assert await p.take_turn([(7, 7)]) == (7, 8)
    assert captured["game_id"] == "game-77" and captured["level_tag"] == "novice"
