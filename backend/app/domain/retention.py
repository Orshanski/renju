"""Ретеншн партий: раздел партии и выбор кандидатов на вытеснение. Чистые функции, без I/O."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .values import GameStatus


class Section(StrEnum):
    CURRENT = "current"
    FINISHED = "finished"
    FAVORITE = "favorite"


def game_section(status: str, favorite: bool) -> Section:
    """Раздел партии по состоянию. Приоритет: favorite → finished → current."""
    if favorite:
        return Section.FAVORITE
    if GameStatus(status).is_finished:
        return Section.FINISHED
    return Section.CURRENT


@dataclass(frozen=True)
class Evictable:
    """Кандидат раздела на вытеснение. sort_key — время старшинства (finished_at для
    завершённых, updated_at для текущих); created_at/id — детерминированный тай-брейк."""

    id: str
    sort_key: datetime
    created_at: datetime


def select_evictions(items: Sequence[Evictable], limit: int) -> list[str]:
    """Держим новейшие `limit` партий раздела; возвращаем id на удаление (старейшие первыми).
    Старшинство: (sort_key, created_at, id) по возрастанию = старейшие сначала."""
    assert limit >= 1  # спека §3: лимит ≥ 1; «без лимита» — это не вызывать функцию (флаг enabled)
    ordered = sorted(items, key=lambda e: (e.sort_key, e.created_at, e.id))
    excess = len(ordered) - limit
    return [e.id for e in ordered[:excess]] if excess > 0 else []
