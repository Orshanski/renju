from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class Level(Base):
    """Текущие настройки уровня сложности (правит админ). Набор фиксирован (сид из levels.toml)."""

    __tablename__ = "levels"

    id: Mapped[str] = mapped_column(primary_key=True)  # "novice".."god"
    name: Mapped[str]
    ordering: Mapped[int]  # порядок показа (слабый→сильный)
    strength: Mapped[int]  # INFO strength 0..100
    timeout_ms: Mapped[int]  # INFO timeout_turn, мс


class EngineSettings(Base):
    """Глобальные настройки движка (одна строка, id=1). Сейчас — только NNUE on/off."""

    __tablename__ = "engine_settings"

    id: Mapped[int] = mapped_column(primary_key=True)  # всегда 1
    nnue: Mapped[bool] = mapped_column(default=True)
