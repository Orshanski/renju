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
    assert isinstance(make_player(User(7), fake_adapter, levels), InteractivePlayer)
    assert isinstance(make_player(Engine("master"), fake_adapter, levels), EnginePlayer)
