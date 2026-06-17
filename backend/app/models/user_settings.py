from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base

DEFAULT_GAMES_LIMIT = 50


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    games_limit: Mapped[int] = mapped_column(default=DEFAULT_GAMES_LIMIT)
    games_limit_enabled: Mapped[bool] = mapped_column(default=True)
    undo_enabled: Mapped[bool] = mapped_column(default=True)
    undo_limit: Mapped[int | None] = mapped_column(default=None)
    undo_after_game_end: Mapped[bool] = mapped_column(default=True)
