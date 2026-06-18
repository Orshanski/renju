from pydantic import BaseModel, Field


class LevelConfigDTO(BaseModel):
    id: str
    name: str
    strength: int
    timeout_ms: int
    max_depth: int
    # потолок от силы (бэк считает; фронт строит диапазон, формулу не дублирует в данных)
    depth_ceiling: int


class EngineConfigDTO(BaseModel):
    levels: list[LevelConfigDTO]
    nnue: bool


class LevelUpdate(BaseModel):
    id: str
    strength: int = Field(ge=0, le=100)
    timeout_ms: int = Field(ge=200, le=30000)
    # санитизация типа/границ движка (не диапазонный гард — диапазон на фронте)
    max_depth: int = Field(ge=1, le=99)


class EngineConfigBody(BaseModel):
    levels: list[LevelUpdate]
    nnue: bool
