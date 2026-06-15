from app.game.event_hub import InMemoryEventHub
from app.rapfi.registry import EngineRegistry


def test_registry_has_engine_adapter_methods():
    for name in ("compute_move", "forbidden_points", "sync_after_undo"):
        assert hasattr(EngineRegistry, name), name


def test_inmemory_hub_has_event_hub_methods():
    for name in ("publish", "cursor", "subscribe"):
        assert hasattr(InMemoryEventHub, name), name
