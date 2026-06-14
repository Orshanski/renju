from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base

# Дефолты ретеншна — в БД (морда настроек — rj-dix). Лимит хранится как int ≥ 1;
# *_enabled=False → раздел без лимита. rj-dix добавит undo-поля аддитивно в эту же таблицу.
DEFAULT_CURRENT_LIMIT = 10
DEFAULT_FINISHED_LIMIT = 50


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    current_limit: Mapped[int] = mapped_column(default=DEFAULT_CURRENT_LIMIT)
    current_limit_enabled: Mapped[bool] = mapped_column(default=True)
    finished_limit: Mapped[int] = mapped_column(default=DEFAULT_FINISHED_LIMIT)
    finished_limit_enabled: Mapped[bool] = mapped_column(default=True)
