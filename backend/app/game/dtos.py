from pydantic import BaseModel


class OpponentBody(BaseModel):
    kind: str = "engine"
    levelId: str


class CreateGameBody(BaseModel):
    opponent: OpponentBody


class LevelDTO(BaseModel):
    id: str
    name: str
