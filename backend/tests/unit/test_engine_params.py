import pytest

from app.domain.engine_params import EngineParams


def test_engine_params_is_frozen():
    p = EngineParams(strength=50, timeout_turn_ms=2000)
    with pytest.raises(AttributeError):  # frozen dataclass → FrozenInstanceError (подкласс)
        p.strength = 99  # type: ignore[misc]
