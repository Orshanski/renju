from datetime import datetime, timedelta

from app.game.repository import InMemoryGameRepository
from app.game.retention_service import RetentionService
from app.game.settings_repository import InMemorySettingsRepository
from app.models.game import Game
from app.models.user_settings import UserSettings

_CTL = {"black": {"kind": "user", "user_id": 1}, "white": {"kind": "engine", "level_id": "master"}}


async def _add_current(repo, gid: str, days_ago: int, now: datetime) -> None:
    await repo.create(
        Game(
            id=gid,
            owner_id=1,
            controllers=_CTL,
            moves=[[7, 7]],
            status="awaiting_move",
            undo_count=0,
            forbidden_log={},
            favorite=False,
            finished_at=None,
            created_at=now - timedelta(days=days_ago + 1),
            updated_at=now - timedelta(days=days_ago),
        )
    )


async def test_enforce_limits_evicts_oldest_current():
    repo = InMemoryGameRepository()
    sr = InMemorySettingsRepository()
    await sr.upsert(
        UserSettings(
            user_id=1,
            current_limit=1,
            current_limit_enabled=True,
            finished_limit=50,
            finished_limit_enabled=True,
        )
    )
    now = datetime(2026, 1, 1, 12, 0, 0)
    await _add_current(repo, "old", days_ago=5, now=now)  # давно не тронутая
    await _add_current(repo, "new", days_ago=1, now=now)  # свежая

    await RetentionService(repo, sr).enforce_limits(1)

    remaining = {g.id for g in await repo.list_by_owner(1)}
    assert remaining == {"new"}  # лимит 1 → старейшая по updated_at вытеснена
