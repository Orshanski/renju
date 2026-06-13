from app.game.controllers import Engine, User, controller_from_json, controller_to_json
from app.game.players import EnginePlayer, InteractivePlayer, make_player


def test_controller_roundtrip():
    assert controller_from_json(controller_to_json(Engine("master"))) == Engine("master")
    assert controller_from_json(controller_to_json(User(7))) == User(7)


async def test_interactive_player_take_turn_none():
    p = InteractivePlayer(7)
    assert await p.take_turn([(7, 7)]) is None


async def test_make_player_dispatch():
    fake_adapter = object()
    levels = {"master": object()}  # level_id → params
    assert isinstance(make_player(User(7), fake_adapter, levels, "g"), InteractivePlayer)
    assert isinstance(make_player(Engine("master"), fake_adapter, levels, "g"), EnginePlayer)


async def test_engine_player_passes_game_id():
    from app.domain.engine_params import EngineParams

    captured = {}

    class FakeReg:
        async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
            captured["game_id"] = game_id
            captured["level_tag"] = level_tag
            return (7, 8)

    levels = {"novice": EngineParams(strength=1, timeout_turn_ms=100)}
    p = make_player(Engine("novice"), FakeReg(), levels, "game-77")
    assert await p.take_turn([(7, 7)]) == (7, 8)
    assert captured["game_id"] == "game-77" and captured["level_tag"] == "novice"
