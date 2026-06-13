from datetime import datetime

from app.domain.retention import Evictable, Section, game_section, select_evictions


def test_section_priority_favorite_over_finished():
    assert game_section("finished_black", favorite=True) is Section.FAVORITE
    assert game_section("finished_draw", favorite=False) is Section.FINISHED
    assert game_section("awaiting_move", favorite=False) is Section.CURRENT
    assert game_section("opponent_thinking", favorite=False) is Section.CURRENT


def _e(i, t, c=None):
    return Evictable(id=i, sort_key=datetime(2026, 1, t), created_at=datetime(2026, 1, c or t))


def test_select_evictions_keeps_newest_n():
    items = [_e("a", 1), _e("b", 2), _e("c", 3)]
    assert select_evictions(items, limit=2) == ["a"]  # самый старый выбывает
    assert select_evictions(items, limit=3) == []  # ровно лимит — никого
    assert select_evictions(items, limit=5) == []  # меньше лимита
    assert select_evictions(items, limit=1) == ["a", "b"]  # держим 1 → выбывают два старейших


def test_select_evictions_tiebreak_created_then_id():
    # равный sort_key → вторичный ключ created_at, затем id
    items = [_e("y", 5, c=2), _e("x", 5, c=1), _e("z", 5, c=1)]
    # держим 1: новейший — max(created_at, id): created_at=2 → y.
    # Выбывают x, z (created=1), старейшие первыми.
    assert select_evictions(items, limit=1) == ["x", "z"]
