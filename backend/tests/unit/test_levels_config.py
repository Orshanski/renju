import pytest

from app.domain.engine_params import EngineParams
from app.levels_config import LevelInfo, load_levels, resolve_level

_SAMPLE = """
[[levels]]
id = "novice"
name = "Новичок"
strength = 5
timeout_turn_ms = 1000

[[levels]]
id = "hard"
name = "Сложный"
strength = 75
timeout_turn_ms = 4000
"""


def test_load_levels_parses_ordered(tmp_path):
    f = tmp_path / "levels.toml"
    f.write_text(_SAMPLE)
    levels = load_levels(f)
    assert [lv.id for lv in levels] == ["novice", "hard"]  # порядок из файла
    assert levels[0] == LevelInfo(
        "novice", "Новичок", EngineParams(strength=5, timeout_turn_ms=1000)
    )
    assert levels[1].params.timeout_turn_ms == 4000


def test_resolve_level_hit_and_miss(tmp_path):
    f = tmp_path / "levels.toml"
    f.write_text(_SAMPLE)
    levels = load_levels(f)
    hit = resolve_level(levels, "hard")
    assert hit is not None
    assert hit.name == "Сложный"
    assert resolve_level(levels, "nope") is None


def test_load_levels_empty_raises(tmp_path):
    f = tmp_path / "levels.toml"
    f.write_text("")  # синтаксически валиден, но пуст
    with pytest.raises(ValueError):
        load_levels(f)
