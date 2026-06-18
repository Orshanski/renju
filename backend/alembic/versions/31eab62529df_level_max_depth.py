"""level max_depth

Revision ID: 31eab62529df
Revises: 67237272bf40
Create Date: 2026-06-18 15:31:07.530416

"""
import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "31eab62529df"
down_revision: str = "67237272bf40"
branch_labels = None
depends_on = None


def _depth_ceiling(strength: int) -> int:
    return 4 + int(24 * (1 - 0.5 ** (strength / 100)))


def upgrade() -> None:
    # 1) колонка с временным дефолтом, затем снять server_default (SQLite-паттерн проекта)
    op.add_column("levels", sa.Column("max_depth", sa.Integer(), nullable=False, server_default="99"))

    # 2) сид уровней: max_depth = depth_ceiling(strength) (Бог → 16 — дефолт-старт; верх 99 крутится в UI)
    conn = op.get_bind()
    for lid, strength in conn.execute(sa.text("SELECT id, strength FROM levels")).fetchall():
        conn.execute(
            sa.text("UPDATE levels SET max_depth = :d WHERE id = :id"),
            {"d": _depth_ceiling(strength), "id": lid},
        )

    # 3) бэкфилл существующих партий: дописать max_depth в engine-сторону controllers
    #    от ЗАМОРОЖЕННОЙ силы партии (ctl["strength"], уже есть после 5d790f3dfeb5)
    rows = conn.execute(sa.text("SELECT id, controllers FROM games")).fetchall()
    for gid, controllers_json in rows:
        controllers = json.loads(controllers_json) if isinstance(controllers_json, str) else controllers_json
        changed = False
        for ctl in controllers.values():
            if ctl.get("kind") == "engine" and "max_depth" not in ctl:
                ctl["max_depth"] = _depth_ceiling(ctl["strength"])  # Бог → 16 (дефолт-старт)
                changed = True
        if changed:
            conn.execute(
                sa.text("UPDATE games SET controllers = :c WHERE id = :id"),
                {"c": json.dumps(controllers), "id": gid},
            )

    # снять server_default — значение задаётся приложением (snapshot)
    with op.batch_alter_table("levels") as batch:
        batch.alter_column("max_depth", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("levels") as batch:
        batch.drop_column("max_depth")
    # JSON-ключ max_depth в games.controllers оставляем — controller_from_json его игнорирует (.get)
