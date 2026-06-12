from datetime import datetime

from sqlalchemy import JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(primary_key=True)  # uuid4
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    controllers: Mapped[dict] = mapped_column(JSON)  # {"black": ctl, "white": ctl}
    moves: Mapped[list] = mapped_column(JSON)  # [[x,y]…]
    status: Mapped[str]
    undo_count: Mapped[int] = mapped_column(default=0)
    forbidden_log: Mapped[dict] = mapped_column(JSON, default=dict)  # {str(len): [[x,y]…]}
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
