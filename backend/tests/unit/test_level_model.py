from app.models.level import EngineSettings, Level


def test_level_columns():
    lv = Level(id="novice", name="Новичок", ordering=0, strength=5, timeout_ms=1000)
    assert (lv.id, lv.strength, lv.timeout_ms, lv.ordering) == ("novice", 5, 1000, 0)


def test_engine_settings_single_row():
    s = EngineSettings(id=1, nnue=True)
    assert s.id == 1 and s.nnue is True
