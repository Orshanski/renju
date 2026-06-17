"""user_settings_v2

Revision ID: 67237272bf40
Revises: 5d790f3dfeb5
Create Date: 2026-06-17 13:05:41.381810

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "67237272bf40"
down_revision: Union[str, Sequence[str], None] = "5d790f3dfeb5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Шаг 1: добавить новые столбцы (пока старые ещё существуют)
    op.add_column("user_settings", sa.Column("games_limit", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("user_settings", sa.Column("games_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("user_settings", sa.Column("undo_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("user_settings", sa.Column("undo_limit", sa.Integer(), nullable=True))
    op.add_column("user_settings", sa.Column("undo_after_game_end", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    # Шаг 2: backfill — MAX сохраняет больший из двух лимитов (не сужаем, не вытесняем)
    op.execute("UPDATE user_settings SET games_limit = MAX(current_limit, finished_limit)")
    # Шаг 3: удалить старые столбцы через batch (SQLite не поддерживает DROP COLUMN напрямую)
    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.drop_column("current_limit")
        batch_op.drop_column("current_limit_enabled")
        batch_op.drop_column("finished_limit")
        batch_op.drop_column("finished_limit_enabled")


def downgrade() -> None:
    op.add_column("user_settings", sa.Column("current_limit", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("user_settings", sa.Column("current_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("user_settings", sa.Column("finished_limit", sa.Integer(), nullable=False, server_default="50"))
    op.add_column("user_settings", sa.Column("finished_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.execute("UPDATE user_settings SET current_limit = games_limit, finished_limit = games_limit")
    with op.batch_alter_table("user_settings") as batch_op:
        batch_op.drop_column("games_limit")
        batch_op.drop_column("games_limit_enabled")
        batch_op.drop_column("undo_enabled")
        batch_op.drop_column("undo_limit")
        batch_op.drop_column("undo_after_game_end")
