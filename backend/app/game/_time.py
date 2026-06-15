"""Вспомогательная функция текущего времени для игрового слоя."""

from datetime import UTC, datetime


def _now() -> datetime:
    """Текущий момент UTC naive — соответствует конвенции datetime-колонок модели Game
    (server_default=func.current_timestamp() без timezone=True → naive UTC в SQLite)."""
    return datetime.now(UTC).replace(tzinfo=None)
