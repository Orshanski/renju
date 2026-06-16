from pydantic import BaseModel, Field


class LevelConfigDTO(BaseModel):
    id: str
    name: str
    strength: int
    timeout_ms: int


class EngineConfigDTO(BaseModel):
    levels: list[LevelConfigDTO]
    nnue: bool


class LevelUpdate(BaseModel):
    id: str
    strength: int = Field(ge=0, le=100)
    timeout_ms: int = Field(ge=200, le=30000)


class EngineConfigBody(BaseModel):
    levels: list[LevelUpdate]
    nnue: bool
