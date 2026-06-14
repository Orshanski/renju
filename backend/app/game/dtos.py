from datetime import datetime

from pydantic import BaseModel


class OpponentBody(BaseModel):
    kind: str = "engine"
    levelId: str


class CreateGameBody(BaseModel):
    opponent: OpponentBody


class LevelDTO(BaseModel):
    id: str
    name: str


class GameSummaryDTO(BaseModel):
    id: str
    status: str
    section: str  # "current"|"finished"|"favorite"
    level_id: str | None  # уровень engine-оппонента, None если нет engine-стороны
    your_color: str | None
    move_count: int
    moves: list[list[int]]  # позиция для мини-доски карточки; уже в строке партии (rj-6ub)
    favorite: bool
    updated_at: datetime | None
    finished_at: datetime | None
