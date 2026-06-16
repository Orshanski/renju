"""engine_config

Revision ID: 5d790f3dfeb5
Revises: eab503b3e51b
Create Date: 2026-06-16 13:52:55.876718

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d790f3dfeb5'
down_revision: Union[str, Sequence[str], None] = 'eab503b3e51b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "levels",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("ordering", sa.Integer(), nullable=False),
        sa.Column("strength", sa.Integer(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
    )
    op.create_table(
        "engine_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nnue", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    levels = sa.table(
        "levels",
        sa.column("id"),
        sa.column("name"),
        sa.column("ordering"),
        sa.column("strength"),
        sa.column("timeout_ms"),
    )
    op.bulk_insert(
        levels,
        [
            {"id": "novice", "name": "Новичок", "ordering": 0, "strength": 5, "timeout_ms": 1000},
            {"id": "easy", "name": "Лёгкий", "ordering": 1, "strength": 15, "timeout_ms": 1500},
            {"id": "low_medium", "name": "Ниже среднего", "ordering": 2, "strength": 35, "timeout_ms": 2000},
            {"id": "high_medium", "name": "Выше среднего", "ordering": 3, "strength": 55, "timeout_ms": 2500},
            {"id": "hard", "name": "Сложный", "ordering": 4, "strength": 75, "timeout_ms": 4000},
            {"id": "master", "name": "Мастер", "ordering": 5, "strength": 90, "timeout_ms": 6000},
            {"id": "god", "name": "Бог", "ordering": 6, "strength": 100, "timeout_ms": 7000},
        ],
    )
    op.bulk_insert(
        sa.table("engine_settings", sa.column("id"), sa.column("nnue")),
        [{"id": 1, "nnue": True}],
    )

    # Бэкфилл: дописать frozen-поля (strength/timeout_ms/nnue) в engine-контроллеры
    # существующих партий.
    _levels_map = {
        "novice":      {"strength": 5,   "timeout_ms": 1000},
        "easy":        {"strength": 15,  "timeout_ms": 1500},
        "low_medium":  {"strength": 35,  "timeout_ms": 2000},
        "high_medium": {"strength": 55,  "timeout_ms": 2500},
        "hard":        {"strength": 75,  "timeout_ms": 4000},
        "master":      {"strength": 90,  "timeout_ms": 6000},
        "god":         {"strength": 100, "timeout_ms": 7000},
    }
    _nnue = True  # зеркалит engine_settings(id=1, nnue=True) из сида выше

    conn = op.get_bind()
    games_table = sa.table("games", sa.column("id"), sa.column("controllers"))
    rows = conn.execute(sa.select(games_table)).fetchall()
    for row in rows:
        game_id = row[0]
        controllers = json.loads(row[1])
        changed = False
        for side, ctl in controllers.items():
            if ctl.get("kind") != "engine":
                continue
            level_id = ctl.get("level_id", "-")
            if level_id == "-" or level_id not in _levels_map:
                continue  # плейсхолдер или неизвестный уровень — пропустить
            if "strength" in ctl and "timeout_ms" in ctl and "nnue" in ctl:
                continue  # уже заморожен
            ctl["strength"] = _levels_map[level_id]["strength"]
            ctl["timeout_ms"] = _levels_map[level_id]["timeout_ms"]
            ctl["nnue"] = _nnue
            changed = True
        if changed:
            conn.execute(
                sa.update(games_table)
                .where(games_table.c.id == game_id)
                .values(controllers=json.dumps(controllers))
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("engine_settings")
    op.drop_table("levels")
