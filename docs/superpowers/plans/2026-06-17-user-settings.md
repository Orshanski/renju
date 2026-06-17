# Настройки пользователя (rj-xt2) — План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать экран «Настройки» — откаты, лимиты партий, смена пароля — полный вертикальный срез бэк + фронт.

**Architecture:** Бэкенд: Alembic-миграция схемы `user_settings` → новый роутер `/api/settings` + `bulk_delete` в `GameService` → TDD. Фронт: `settings.api.ts` + `bulkDeleteGames` в `game/api.ts` → полная замена заглушки `SettingsPage.tsx`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, SQLite; React 18, TypeScript, Vite, Vitest, CSS Modules.

## Global Constraints

- Все backend-команды запускать из `backend/` через `uv run …`
- pytest гонять **последовательно** (не `-n auto`): `uv run pytest -q`
- CSS: только `@value`-токены из `../styles/tokens.module.css`, никаких inline hex
- `games_limit` диапазон: 10..100; `undo_limit`: 1..999 или `null` (∞)
- `new_password`: `min_length=6, max_length=72` (bcrypt-ограничение)
- Роутинг фронта (`/settings → SettingsPage`) уже настроен в `App.tsx` — не трогать

---

### Task 1: Миграция, модель, репозиторий, RetentionService

**Files:**
- Modify: `backend/app/models/user_settings.py`
- Modify: `backend/app/game/settings_repository.py`
- Modify: `backend/app/game/retention_service.py`
- Create: `backend/alembic/versions/<id>_user_settings_v2.py`

**Interfaces:**
- Produces: `UserSettings` с полями `games_limit: int`, `games_limit_enabled: bool`, `undo_enabled: bool`, `undo_limit: int | None`, `undo_after_game_end: bool`; константа `DEFAULT_GAMES_LIMIT = 50`
- Produces: `SettingsRepository.get_or_default(user_id) -> UserSettings`, `upsert(settings) -> None`

- [ ] **Step 1: Обновить модель `user_settings.py`**

```python
# backend/app/models/user_settings.py
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
```

- [ ] **Step 2: Обновить репозиторий `settings_repository.py`**

```python
# backend/app/game/settings_repository.py
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.user_settings import DEFAULT_GAMES_LIMIT, UserSettings


class SettingsRepository(Protocol):
    async def get_or_default(self, user_id: int) -> UserSettings: ...
    async def upsert(self, settings: UserSettings) -> None: ...


class SqlSettingsRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def get_or_default(self, user_id: int) -> UserSettings:
        obj = await self._s.get(UserSettings, user_id)
        if obj is not None:
            return obj
        return UserSettings(
            user_id=user_id,
            games_limit=DEFAULT_GAMES_LIMIT,
            games_limit_enabled=True,
            undo_enabled=True,
            undo_limit=None,
            undo_after_game_end=True,
        )

    async def upsert(self, settings: UserSettings) -> None:
        await self._s.merge(settings)
        await self._s.commit()


class InMemorySettingsRepository:
    def __init__(self):
        self._d: dict[int, UserSettings] = {}

    async def get_or_default(self, user_id: int) -> UserSettings:
        if user_id in self._d:
            return self._d[user_id]
        return UserSettings(
            user_id=user_id,
            games_limit=DEFAULT_GAMES_LIMIT,
            games_limit_enabled=True,
            undo_enabled=True,
            undo_limit=None,
            undo_after_game_end=True,
        )

    async def upsert(self, settings: UserSettings) -> None:
        self._d[settings.user_id] = settings
```

- [ ] **Step 3: Обновить RetentionService**

В `backend/app/game/retention_service.py` заменить `current_limit_enabled/current_limit` и `finished_limit_enabled/finished_limit` на единый `games_limit_enabled/games_limit` в обоих методах:

```python
# backend/app/game/retention_service.py
"""Вытеснение партий по лимитам (ретеншн). Выделено из GameService."""

from datetime import datetime

from ..domain.retention import Evictable, Section, game_section, select_evictions
from ._time import _now
from .repository import GameRepository
from .settings_repository import SettingsRepository


class RetentionService:
    def __init__(self, repo: GameRepository, settings_repo: SettingsRepository):
        self._repo = repo
        self._settings_repo = settings_repo

    async def evict_current(self, owner_id: int) -> None:
        """Подрезает раздел CURRENT для владельца до games_limit."""
        settings = await self._settings_repo.get_or_default(owner_id)
        if not settings.games_limit_enabled:
            return
        games = await self._repo.list_by_owner(owner_id)
        candidates: list[Evictable] = []
        for g in games:
            if game_section(g.status, bool(g.favorite)) is not Section.CURRENT:
                continue
            sort_key: datetime = (
                g.updated_at if g.updated_at is not None else (g.created_at or _now())
            )
            created_at: datetime = g.created_at if g.created_at is not None else _now()
            candidates.append(Evictable(id=g.id, sort_key=sort_key, created_at=created_at))
        for game_id in select_evictions(candidates, settings.games_limit):
            await self._repo.delete(game_id)

    async def evict_finished(self, owner_id: int) -> None:
        """Подрезает раздел FINISHED для владельца до games_limit."""
        settings = await self._settings_repo.get_or_default(owner_id)
        if not settings.games_limit_enabled:
            return
        games = await self._repo.list_by_owner(owner_id)
        candidates: list[Evictable] = []
        for g in games:
            if game_section(g.status, bool(g.favorite)) is not Section.FINISHED:
                continue
            sort_key = g.finished_at if g.finished_at is not None else (g.created_at or _now())
            created_at: datetime = g.created_at if g.created_at is not None else _now()
            candidates.append(Evictable(id=g.id, sort_key=sort_key, created_at=created_at))
        for game_id in select_evictions(candidates, settings.games_limit):
            await self._repo.delete(game_id)

    async def enforce_limits(self, owner_id: int) -> None:
        """Подрезает оба раздела (CURRENT + FINISHED) до лимита."""
        await self.evict_current(owner_id)
        await self.evict_finished(owner_id)
```

- [ ] **Step 4: Создать Alembic-миграцию**

Запустить генерацию пустой миграции:
```bash
cd backend
uv run alembic revision -m "user_settings_v2"
```

Alembic создаст файл `alembic/versions/<id>_user_settings_v2.py`. Открыть файл, записать `<id>` (строка вида `"a1b2c3d4e5f6"`), и заменить содержимое функций `upgrade`/`downgrade`:

```python
# backend/alembic/versions/<id>_user_settings_v2.py
"""user_settings_v2

Revision ID: <id>  ← значение из сгенерированного файла
Revises: 5d790f3dfeb5
Create Date: <дата>
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "<id>"  # ← значение из сгенерированного файла
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
```

- [ ] **Step 5: Проверить что alembic upgrade проходит**

```bash
cd backend
uv run alembic upgrade head
```
Ожидание: `INFO  [alembic.runtime.migration] Running upgrade 5d790f3dfeb5 -> <id>, user_settings_v2`

- [ ] **Step 6: Проверить ruff**

```bash
cd backend
uv run ruff check app
```
Ожидание: no errors

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/user_settings.py \
        backend/app/game/settings_repository.py \
        backend/app/game/retention_service.py \
        backend/alembic/versions/<id>_user_settings_v2.py
git commit -m "feat(rj-xt2): user_settings v2 — один games_limit + undo-поля"
```

---

### Task 2: Обновить сломанные тесты

**Files:**
- Modify: `backend/tests/unit/test_settings_repository.py`
- Modify: `backend/tests/unit/test_retention_service.py`
- Modify: `backend/tests/unit/test_game_service_contour.py`

**Interfaces:**
- Consumes: `UserSettings`, `DEFAULT_GAMES_LIMIT` из Task 1

- [ ] **Step 1: Переписать `test_settings_repository.py`**

```python
# backend/tests/unit/test_settings_repository.py
from app.game.settings_repository import InMemorySettingsRepository, SqlSettingsRepository
from app.models.user_settings import DEFAULT_GAMES_LIMIT, UserSettings


async def test_inmemory_get_or_default_returns_defaults():
    r = InMemorySettingsRepository()
    s = await r.get_or_default(42)
    assert s.games_limit == DEFAULT_GAMES_LIMIT
    assert s.games_limit_enabled is True
    assert s.undo_enabled is True
    assert s.undo_limit is None
    assert s.undo_after_game_end is True


async def test_inmemory_upsert_and_get():
    r = InMemorySettingsRepository()
    settings = UserSettings(
        user_id=7,
        games_limit=20,
        games_limit_enabled=False,
        undo_enabled=False,
        undo_limit=3,
        undo_after_game_end=False,
    )
    await r.upsert(settings)
    got = await r.get_or_default(7)
    assert got.games_limit == 20
    assert got.games_limit_enabled is False
    assert got.undo_enabled is False
    assert got.undo_limit == 3
    assert got.undo_after_game_end is False


async def test_inmemory_upsert_overwrites():
    r = InMemorySettingsRepository()
    s1 = UserSettings(user_id=3, games_limit=10, games_limit_enabled=True,
                      undo_enabled=True, undo_limit=None, undo_after_game_end=True)
    await r.upsert(s1)
    s2 = UserSettings(user_id=3, games_limit=100, games_limit_enabled=False,
                      undo_enabled=False, undo_limit=5, undo_after_game_end=False)
    await r.upsert(s2)
    got = await r.get_or_default(3)
    assert got.games_limit == 100
    assert got.games_limit_enabled is False
    assert got.undo_limit == 5


async def test_sql_get_or_default_no_row(session):
    from app.dal import users as udal
    uid = await udal.create_user(session, "bob_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    s = await r.get_or_default(uid)
    assert s.games_limit == DEFAULT_GAMES_LIMIT
    assert s.games_limit_enabled is True
    assert s.undo_enabled is True
    assert s.undo_limit is None


async def test_sql_upsert_and_get(session, engine):
    from app.dal import users as udal
    from app.db.session import make_sessionmaker
    uid = await udal.create_user(session, "carol_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    settings = UserSettings(user_id=uid, games_limit=30, games_limit_enabled=True,
                            undo_enabled=True, undo_limit=10, undo_after_game_end=False)
    await r.upsert(settings)
    async with make_sessionmaker(engine)() as s2:
        got = await SqlSettingsRepository(s2).get_or_default(uid)
    assert got.games_limit == 30
    assert got.undo_limit == 10
    assert got.undo_after_game_end is False


async def test_sql_upsert_overwrites(session, engine):
    from app.dal import users as udal
    from app.db.session import make_sessionmaker
    uid = await udal.create_user(session, "dave_settings", "pw")
    await session.commit()
    r = SqlSettingsRepository(session)
    s1 = UserSettings(user_id=uid, games_limit=50, games_limit_enabled=True,
                      undo_enabled=True, undo_limit=None, undo_after_game_end=True)
    await r.upsert(s1)
    s2 = UserSettings(user_id=uid, games_limit=20, games_limit_enabled=False,
                      undo_enabled=False, undo_limit=2, undo_after_game_end=False)
    await r.upsert(s2)
    async with make_sessionmaker(engine)() as s3:
        got = await SqlSettingsRepository(s3).get_or_default(uid)
    assert got.games_limit == 20
    assert got.games_limit_enabled is False
    assert got.undo_limit == 2
```

- [ ] **Step 2: Обновить `test_retention_service.py`**

В функции `test_enforce_limits_evicts_oldest_current` заменить создание `UserSettings`:

```python
# было:
await sr.upsert(
    UserSettings(
        user_id=1,
        current_limit=1,
        current_limit_enabled=True,
        finished_limit=50,
        finished_limit_enabled=True,
    )
)
# стало:
await sr.upsert(
    UserSettings(
        user_id=1,
        games_limit=1,
        games_limit_enabled=True,
        undo_enabled=True,
        undo_limit=None,
        undo_after_game_end=True,
    )
)
```

- [ ] **Step 3: Обновить `test_game_service_contour.py` — 5 функций**

В каждой функции найти блок `await sr.upsert(UserSettings(...))` и заменить на `games_limit`/`games_limit_enabled`:

**`test_finish_sets_finished_at_and_evicts_over_limit` (~строка 397):**
```python
# было: current_limit=10, current_limit_enabled=True, finished_limit=2, finished_limit_enabled=True
# стало:
await sr.upsert(UserSettings(
    user_id=1, games_limit=2, games_limit_enabled=True,
    undo_enabled=True, undo_limit=None, undo_after_game_end=True,
))
```

**`test_create_evicts_current_over_limit` (~строка 490):**
```python
# было: current_limit=2, current_limit_enabled=True, finished_limit=50, finished_limit_enabled=True
# стало:
await sr.upsert(UserSettings(
    user_id=1, games_limit=2, games_limit_enabled=True,
    undo_enabled=True, undo_limit=None, undo_after_game_end=True,
))
```

**`test_favorite_only_finished_and_exempt_from_limit` (~строка 559):**
```python
# было: current_limit=10, current_limit_enabled=True, finished_limit=1, finished_limit_enabled=True
# стало:
await sr.upsert(UserSettings(
    user_id=1, games_limit=1, games_limit_enabled=True,
    undo_enabled=True, undo_limit=None, undo_after_game_end=True,
))
```

**`test_unfavorite_returns_to_finished_and_rechecks_limit` (~строка 661):**
```python
# было: current_limit=10, current_limit_enabled=True, finished_limit=1, finished_limit_enabled=True
# стало:
await sr.upsert(UserSettings(
    user_id=1, games_limit=1, games_limit_enabled=True,
    undo_enabled=True, undo_limit=None, undo_after_game_end=True,
))
```

**`test_enforce_limits_trims_both_sections` (~строка 747):**
```python
# было: current_limit=1, current_limit_enabled=True, finished_limit=1, finished_limit_enabled=True
# стало:
await sr.upsert(UserSettings(
    user_id=1, games_limit=1, games_limit_enabled=True,
    undo_enabled=True, undo_limit=None, undo_after_game_end=True,
))
```

- [ ] **Step 4: Прогнать тесты — должны быть зелёными**

```bash
cd backend
uv run pytest tests/unit/test_settings_repository.py tests/unit/test_retention_service.py tests/unit/test_game_service_contour.py -v
```
Ожидание: все PASSED

- [ ] **Step 5: Полный прогон**

```bash
cd backend
uv run pytest -q
```
Ожидание: все PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/tests/unit/test_settings_repository.py \
        backend/tests/unit/test_retention_service.py \
        backend/tests/unit/test_game_service_contour.py
git commit -m "test(rj-xt2): обновить тесты под новую схему UserSettings"
```

---

### Task 3: Исправить GameService.undo

**Files:**
- Modify: `backend/app/game/service.py:245-260`

**Interfaces:**
- Consumes: `SettingsRepository.get_or_default` из Task 1
- Consumes: `UndoPolicy(enabled, limit, after_game_end)` из `domain/undo.py`

- [ ] **Step 1: Написать падающий тест**

Добавить в `backend/tests/unit/test_game_service_contour.py`. Паттерн: `_create_game(human_color="black")` → партия в `opponent_thinking` → `advance()` → FakeAdapter ходит → `awaiting_move` → пробуем `undo`.

```python
async def test_undo_respects_policy_disabled():
    """Если undo_enabled=False, undo должен отклоняться."""
    import pytest
    from app.domain.errors import UndoRejected
    from app.models.user_settings import UserSettings

    sr = InMemorySettingsRepository()
    await sr.upsert(UserSettings(
        user_id=1, games_limit=50, games_limit_enabled=True,
        undo_enabled=False, undo_limit=None, undo_after_game_end=True,
    ))
    svc = _svc(settings_repo=sr)
    fake = _fake(svc)
    # human=WHITE, engine=BLACK; create → awaiting_move (белый-человек ходит)
    g = await _create_game(svc, owner_id=1, human_color="white")
    g = await svc.submit_move(g.id, user_id=1, point=(8, 8))
    fake.move = (6, 6)
    await svc.advance(g)  # движок-чёрный ходит → awaiting_move, есть что откатить
    with pytest.raises(UndoRejected):
        await svc.undo(g.id, user_id=1)  # отклонён: undo_enabled=False


async def test_undo_respects_policy_limit():
    """Если undo_limit=1, второй undo должен отклоняться."""
    import pytest
    from app.domain.errors import UndoRejected
    from app.models.user_settings import UserSettings

    sr = InMemorySettingsRepository()
    await sr.upsert(UserSettings(
        user_id=1, games_limit=50, games_limit_enabled=True,
        undo_enabled=True, undo_limit=1, undo_after_game_end=True,
    ))
    svc = _svc(settings_repo=sr)
    fake = _fake(svc)
    # human=WHITE, engine=BLACK; create → awaiting_move
    g = await _create_game(svc, owner_id=1, human_color="white")
    g = await svc.submit_move(g.id, user_id=1, point=(8, 8))
    fake.move = (6, 6)
    await svc.advance(g)  # moves=[[7,7],[8,8],[6,6]], awaiting_move

    await svc.undo(g.id, user_id=1)  # первый undo → ок, undo_count=1

    g = await svc.get_game(g.id, user_id=1)
    g = await svc.submit_move(g.id, user_id=1, point=(8, 8))
    fake.move = (5, 5)
    await svc.advance(g)

    with pytest.raises(UndoRejected):
        await svc.undo(g.id, user_id=1)  # второй undo → LIMIT_REACHED
```

- [ ] **Step 2: Запустить — убедиться что FAIL**

```bash
cd backend
uv run pytest tests/unit/test_game_service_contour.py::test_undo_respects_policy_disabled tests/unit/test_game_service_contour.py::test_undo_respects_policy_limit -v
```
Ожидание: FAIL (undo не отклоняется, политика игнорируется)

- [ ] **Step 3: Исправить `service.py`**

В `backend/app/game/service.py` найти метод `undo` (~строка 245) и заменить:

```python
# было:
async def undo(self, game_id: str, user_id: int) -> Game:
    game = await self._load_owned(game_id, user_id)
    check_undo(
        policy=UndoPolicy(),
        status=GameStatus(game.status),
        undo_count=game.undo_count,
    )

# стало:
async def undo(self, game_id: str, user_id: int) -> Game:
    game = await self._load_owned(game_id, user_id)
    settings = await self._settings_repo.get_or_default(user_id)
    policy = UndoPolicy(
        enabled=settings.undo_enabled,
        limit=settings.undo_limit,
        after_game_end=settings.undo_after_game_end,
    )
    check_undo(
        policy=policy,
        status=GameStatus(game.status),
        undo_count=game.undo_count,
    )
    # остаток метода без изменений
```

- [ ] **Step 4: Прогнать — PASS**

```bash
cd backend
uv run pytest tests/unit/test_game_service_contour.py::test_undo_respects_policy_disabled tests/unit/test_game_service_contour.py::test_undo_respects_policy_limit -v
```
Ожидание: PASSED

- [ ] **Step 5: Полный прогон**

```bash
cd backend
uv run pytest -q
```
Ожидание: все PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/game/service.py backend/tests/unit/test_game_service_contour.py
git commit -m "fix(rj-xt2): undo использует UndoPolicy из настроек пользователя"
```

---

### Task 4: Роутер /api/settings, bulk_delete, DELETE /api/games

**Files:**
- Create: `backend/app/routers/settings.py`
- Modify: `backend/app/game/service.py` (добавить `bulk_delete`)
- Modify: `backend/app/routers/games.py` (добавить `DELETE /api/games`)
- Modify: `backend/app/app_factory.py` (регистрация роутера)

**Interfaces:**
- Produces: `GET /api/settings → SettingsDTO`, `PUT /api/settings → SettingsDTO`, `PUT /api/settings/password → 204`, `DELETE /api/games?section=current|finished → 204`

- [ ] **Step 1: Добавить `bulk_delete` в `GameService`**

В конец класса `GameService` в `backend/app/game/service.py` добавить:

```python
async def bulk_delete(self, user_id: int, section: Section) -> int:
    """Удалить все партии пользователя в указанном разделе (current или finished)."""
    games = await self._repo.list_by_owner(user_id)
    ids = [g.id for g in games if game_section(g.status, g.favorite) is section]
    for game_id in ids:
        await self._repo.delete(game_id)
    return len(ids)
```

Убедиться что в импортах `service.py` есть `from ..domain.retention import Section, game_section` (уже есть).

- [ ] **Step 2: Создать `routers/settings.py`**

```python
# backend/app/routers/settings.py
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, bump_token_epoch, hash_password, verify_password
from ..db.deps import get_session
from ..exceptions import BadInputError
from ..game.settings_repository import SqlSettingsRepository
from ..models.user import User
from ..models.user_settings import UserSettings
from .auth import current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsDTO(BaseModel):
    games_limit: int
    games_limit_enabled: bool
    undo_enabled: bool
    undo_limit: int | None
    undo_after_game_end: bool


class SettingsBody(BaseModel):
    games_limit: int = Field(ge=10, le=100)
    games_limit_enabled: bool
    undo_enabled: bool
    undo_limit: int | None = Field(default=None, ge=1, le=999)
    undo_after_game_end: bool


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=72)
    new_password: str = Field(min_length=6, max_length=72)


def _to_dto(s: UserSettings) -> SettingsDTO:
    return SettingsDTO(
        games_limit=s.games_limit,
        games_limit_enabled=s.games_limit_enabled,
        undo_enabled=s.undo_enabled,
        undo_limit=s.undo_limit,
        undo_after_game_end=s.undo_after_game_end,
    )


@router.get("", response_model=SettingsDTO)
async def get_settings(
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    repo = SqlSettingsRepository(session)
    return _to_dto(await repo.get_or_default(user.user_id))


@router.put("", response_model=SettingsDTO)
async def put_settings(
    body: SettingsBody,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    from ..game.deps import build_game_service
    repo = SqlSettingsRepository(session)
    settings = UserSettings(
        user_id=user.user_id,
        games_limit=body.games_limit,
        games_limit_enabled=body.games_limit_enabled,
        undo_enabled=body.undo_enabled,
        undo_limit=body.undo_limit,
        undo_after_game_end=body.undo_after_game_end,
    )
    await repo.upsert(settings)
    svc = build_game_service(request, session)
    await svc.enforce_limits(user.user_id)
    return _to_dto(await repo.get_or_default(user.user_id))


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordBody,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    db_user = await session.get(User, user.user_id)
    if db_user is None or not verify_password(body.current_password, db_user.password_hash):
        raise BadInputError("Неверный текущий пароль")
    db_user.password_hash = hash_password(body.new_password)
    await session.flush()
    new_epoch = await bump_token_epoch(session, user.user_id)
    await session.commit()
    if new_epoch is None:
        return  # guard: строка не найдена (теоретически невозможно — пользователь только что проверен)
    # Обновить epoch в cookie через rolling refresh (middleware/refresh.py)
    request.state.refresh = {"user_id": user.user_id, "role": user.role, "epoch": new_epoch}
```

- [ ] **Step 3: Добавить DELETE /api/games в `routers/games.py`**

Добавить после импортов нужные типы и эндпоинт:

```python
# В начало файла добавить в импорты:
from ..domain.retention import Section
```

Добавить эндпоинт (после `delete_game`):

```python
@router.delete("/games", status_code=204)
async def bulk_delete_games(
    section: Literal["current", "finished"],
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    await service.bulk_delete(user.user_id, Section(section))
```

Добавить `Literal` в импорт `typing`:
```python
from typing import Annotated, Literal
```

- [ ] **Step 4: Зарегистрировать роутер в `app_factory.py`**

```python
# Добавить импорт (рядом с другими роутерами):
from .routers import settings as settings_router

# Добавить регистрацию (рядом с остальными include_router):
app.include_router(settings_router.router)
```

- [ ] **Step 5: Проверить ruff**

```bash
cd backend
uv run ruff check app
```
Ожидание: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/settings.py \
        backend/app/game/service.py \
        backend/app/routers/games.py \
        backend/app/app_factory.py
git commit -m "feat(rj-xt2): роутер /api/settings + bulk_delete партий"
```

---

### Task 5: Тесты бэкенда

**Files:**
- Modify: `backend/tests/unit/test_migration.py`
- Create: `backend/tests/api/test_settings_router.py`

**Interfaces:**
- Consumes: `/api/settings` GET/PUT, `/api/settings/password` PUT, `/api/games?section=` DELETE из Task 4

- [ ] **Step 1: Добавить backfill-тест в `test_migration.py`**

```python
def test_backfill_user_settings_v2(tmp_path, monkeypatch):
    """games_limit = MAX(current_limit, finished_limit) после миграции user_settings_v2."""
    import subprocess

    from sqlalchemy import create_engine, text

    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))

    # Поднять схему до состояния ДО нашей миграции
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "5d790f3dfeb5"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr

    # Вставить пользователя и строку user_settings со старыми полями
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (id, username, password_hash, role, token_epoch) "
            "VALUES (1, 'alice', 'x', 'user', 0)"
        ))
        conn.execute(text(
            "INSERT INTO user_settings "
            "(user_id, current_limit, current_limit_enabled, finished_limit, finished_limit_enabled) "
            "VALUES (1, 30, 1, 70, 1)"
        ))
    eng.dispose()

    # Накатить нашу миграцию
    r2 = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True, text=True,
    )
    assert r2.returncode == 0, r2.stderr

    # Проверить backfill
    eng2 = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng2.connect() as conn:
        row = conn.execute(text(
            "SELECT games_limit, games_limit_enabled, undo_enabled, undo_after_game_end "
            "FROM user_settings WHERE user_id=1"
        )).fetchone()
    eng2.dispose()

    assert row is not None
    assert row[0] == 70  # MAX(30, 70)
    assert row[1] == 1   # games_limit_enabled
    assert row[2] == 1   # undo_enabled default
    assert row[3] == 1   # undo_after_game_end default
```

- [ ] **Step 2: Прогнать тест миграции**

```bash
cd backend
uv run pytest tests/unit/test_migration.py -v
```
Ожидание: все PASSED

- [ ] **Step 3: Создать `test_settings_router.py`**

```python
# backend/tests/api/test_settings_router.py
import pytest


async def _login(app, client, username="alice", password="pw"):
    from app.dal import users as dal
    async with app.state.sessionmaker() as s:
        if not await dal.get_user_by_username(s, username):
            await dal.create_user(s, username, password)
            await s.commit()
    await client.post("/api/auth/login", json={"username": username, "password": password})


async def test_get_settings_returns_defaults(app, client):
    await _login(app, client)
    r = await client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["games_limit"] == 50
    assert body["games_limit_enabled"] is True
    assert body["undo_enabled"] is True
    assert body["undo_limit"] is None
    assert body["undo_after_game_end"] is True


async def test_get_settings_requires_auth(app, client):
    r = await client.get("/api/settings")
    assert r.status_code == 401


async def test_put_settings_saves_and_returns(app, client):
    await _login(app, client)
    body = {
        "games_limit": 30,
        "games_limit_enabled": True,
        "undo_enabled": False,
        "undo_limit": None,
        "undo_after_game_end": False,
    }
    r = await client.put("/api/settings", json=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["games_limit"] == 30
    assert resp["undo_enabled"] is False
    assert resp["undo_after_game_end"] is False


async def test_put_settings_validates_limit_range(app, client):
    await _login(app, client)
    r = await client.put("/api/settings", json={
        "games_limit": 5,  # < 10 → 422
        "games_limit_enabled": True,
        "undo_enabled": True,
        "undo_limit": None,
        "undo_after_game_end": True,
    })
    assert r.status_code == 422


async def test_change_password_wrong_current(app, client):
    await _login(app, client)
    r = await client.put("/api/settings/password", json={
        "current_password": "wrong",
        "new_password": "newpass123",
    })
    assert r.status_code == 400


async def test_change_password_success_keeps_session(app, client):
    await _login(app, client)
    r = await client.put("/api/settings/password", json={
        "current_password": "pw",
        "new_password": "newpass123",
    })
    assert r.status_code == 204
    # Текущая сессия должна работать (cookie обновлён)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200


async def test_change_password_new_epoch_in_cookie(app, client):
    """После смены пароля cookie содержит новый token_epoch."""
    from app.auth import decode_token
    from app.config import Settings

    await _login(app, client)
    # Запомнить текущий epoch
    old_cookie = client.cookies.get("renju_token")
    old_epoch = decode_token(old_cookie, Settings()).get("tep", 0)

    r = await client.put("/api/settings/password", json={
        "current_password": "pw",
        "new_password": "newpass123",
    })
    assert r.status_code == 204

    new_cookie = client.cookies.get("renju_token")
    new_epoch = decode_token(new_cookie, Settings()).get("tep", 0)
    assert new_epoch == old_epoch + 1


async def test_bulk_delete_current(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()  # избежать реального движка
    await games_api.seed_login(app, client)
    # Создать две партии
    r1 = await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    assert r1.status_code == 200
    r2 = await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    assert r2.status_code == 200

    r = await client.delete("/api/games?section=current")
    assert r.status_code == 204

    # Список должен быть пустым
    games = await client.get("/api/games/summary?section=current")
    assert games.json() == []


async def test_bulk_delete_favorite_returns_422(app, client):
    await _login(app, client)
    r = await client.delete("/api/games?section=favorite")
    assert r.status_code == 422
```

- [ ] **Step 4: Прогнать тесты роутера**

```bash
cd backend
uv run pytest tests/api/test_settings_router.py -v
```
Ожидание: все PASSED

- [ ] **Step 5: Полный прогон**

```bash
cd backend
uv run pytest -q
```
Ожидание: все PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/tests/unit/test_migration.py \
        backend/tests/api/test_settings_router.py
git commit -m "test(rj-xt2): тесты миграции backfill + API настроек"
```

---

### Task 6: Frontend API

**Files:**
- Create: `frontend/src/settings.api.ts`
- Modify: `frontend/src/game/api.ts`

**Interfaces:**
- Produces: `UserSettings` interface, `getSettings()`, `saveSettings()`, `changePassword()`, `bulkDeleteGames()`

- [ ] **Step 1: Создать `settings.api.ts`**

```typescript
// frontend/src/settings.api.ts
import { apiRequest } from "./api/client";

export interface UserSettings {
  games_limit: number;
  games_limit_enabled: boolean;
  undo_enabled: boolean;
  undo_limit: number | null;  // null = ∞
  undo_after_game_end: boolean;
}

export function getSettings(): Promise<UserSettings> {
  return apiRequest<UserSettings>("GET", "/api/settings");
}

export function saveSettings(body: UserSettings): Promise<UserSettings> {
  return apiRequest<UserSettings>("PUT", "/api/settings", body);
}

export function changePassword(current_password: string, new_password: string): Promise<void> {
  return apiRequest<void>("PUT", "/api/settings/password", { current_password, new_password });
}
```

- [ ] **Step 2: Добавить `bulkDeleteGames` в `game/api.ts`**

Добавить в конец `frontend/src/game/api.ts`:

```typescript
export function bulkDeleteGames(section: "current" | "finished"): Promise<void> {
  return apiRequest<void>("DELETE", `/api/games?section=${section}`);
}
```

- [ ] **Step 3: TypeScript-проверка**

```bash
cd frontend
npx tsc --noEmit
```
Ожидание: 0 ошибок

- [ ] **Step 4: Commit**

```bash
git add frontend/src/settings.api.ts frontend/src/game/api.ts
git commit -m "feat(rj-xt2): settings.api.ts + bulkDeleteGames"
```

---

### Task 7: SettingsPage (фронт)

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/pages/SettingsPage.module.css`
- Modify: `frontend/src/pages/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: `getSettings`, `saveSettings`, `changePassword` из Task 6
- Consumes: `bulkDeleteGames` из `game/api.ts` Task 6

- [ ] **Step 1: Расширить `SettingsPage.module.css`**

```css
/* frontend/src/pages/SettingsPage.module.css */
@value sumi, sumiSoft, sumiFaint, vermillion, vermillionDeep, paper, okGreen, r, rInput, fontSerif, fontSans from "../styles/tokens.module.css";

.wrap {
  max-width: 680px;
  margin: 0 auto;
  padding: 0 0 48px;
}

.eyebrow {
  font-family: fontSans;
  font-size: 11px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: sumiFaint;
  margin-bottom: 6px;
}

.title {
  font-family: fontSerif;
  font-size: 28px;
  font-weight: 700;
  color: sumi;
  margin: 0 0 28px;
}

.sectionTitle {
  font-family: fontSans;
  font-size: 11px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: sumiFaint;
  margin: 30px 0 14px;
}

.settings {
  max-width: 680px;
}

.setrow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 20px 0;
  border-bottom: 1px solid rgba(60, 45, 25, 0.14);
}

.setrowLabel {
  font-family: fontSerif;
  font-weight: 600;
  font-size: 16px;
  color: sumi;
}

.setrowDesc {
  color: sumiSoft;
  font-family: fontSans;
  font-size: 13.5px;
  font-weight: 300;
  margin-top: 3px;
  max-width: 420px;
}

/* Toggle */
.toggle {
  width: 52px;
  height: 30px;
  border-radius: 30px;
  background: rgba(60, 45, 25, 0.22);
  position: relative;
  cursor: pointer;
  transition: background 0.2s;
  flex-shrink: 0;
}

.toggle::after {
  content: "";
  position: absolute;
  top: 3px;
  left: 3px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #fbf6ea;
  transition: left 0.2s;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.toggleOn {
  composes: toggle;
  background: okGreen;
}

.toggleOn::after {
  left: 25px;
}

/* Stepper */
.stepper {
  display: flex;
  align-items: center;
  border: 1px solid rgba(60, 45, 25, 0.25);
  border-radius: 10px;
  overflow: hidden;
  flex-shrink: 0;
}

.stepperBtn {
  width: 40px;
  height: 40px;
  border: none;
  background: #f3e9d4;
  font-size: 18px;
  cursor: pointer;
  color: sumi;
  font-family: fontSans;
}

.stepperBtn:hover {
  background: #ecdfc4;
}

.stepperNum {
  width: 64px;
  text-align: center;
  font-weight: 600;
  font-family: fontSans;
  color: sumi;
  font-variant-numeric: tabular-nums;
}

/* Buttons */
.saveBtn {
  margin-top: 16px;
  padding: 10px 24px;
  background: vermillion;
  color: #fff;
  border: none;
  border-radius: r;
  font-family: fontSans;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.saveBtn:hover:not(:disabled) {
  background: vermillionDeep;
}

.saveBtn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dangerRowBtn {
  padding: 10px 16px;
  background: transparent;
  border: 1px solid rgba(189, 51, 38, 0.4);
  border-radius: rInput;
  font-family: fontSans;
  font-size: 13px;
  color: vermillion;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  flex-shrink: 0;
}

.dangerRowBtn:hover {
  background: rgba(189, 51, 38, 0.06);
  border-color: vermillion;
}

/* Пароль */
.passwordBlock {
  margin-top: 30px;
  max-width: 440px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.field label {
  font-family: fontSans;
  font-size: 13px;
  color: sumiFaint;
  font-weight: 600;
}

.field input[type="password"] {
  padding: 8px 12px;
  border: 1px solid rgba(60, 45, 25, 0.25);
  border-radius: rInput;
  font-family: fontSans;
  font-size: 14px;
  color: sumi;
  background: #fff;
  outline: none;
  transition: border-color 0.15s;
}

.field input[type="password"]:focus {
  border-color: vermillion;
}

.hint {
  color: sumiFaint;
  font-family: fontSans;
  font-size: 12px;
  margin: -8px 0 12px;
}

.errMsg {
  color: vermillion;
  font-family: fontSans;
  font-size: 13px;
  margin: 0 0 12px;
}

/* Диалоги */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(36, 29, 22, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  background: paper;
  border-radius: r;
  padding: 28px 32px;
  min-width: 320px;
  max-width: 440px;
  width: 100%;
  box-shadow: 0 18px 40px -18px rgba(40, 28, 14, 0.55);
}

.modalTitle {
  font-family: fontSans;
  font-size: 17px;
  font-weight: 700;
  color: sumi;
  margin: 0 0 16px;
}

.modalBody {
  font-family: fontSans;
  font-size: 14px;
  color: sumiSoft;
  margin: 0 0 20px;
}

.modalFooter {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.cancelBtn {
  padding: 9px 20px;
  background: transparent;
  border: 1px solid rgba(60, 45, 25, 0.25);
  border-radius: r;
  font-family: fontSans;
  font-size: 14px;
  color: sumiSoft;
  cursor: pointer;
  transition: border-color 0.15s;
}

.cancelBtn:hover {
  border-color: sumi;
}

.dangerBtn {
  padding: 9px 22px;
  background: vermillionDeep;
  color: #fff;
  border: none;
  border-radius: r;
  font-family: fontSans;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}

.dangerBtn:hover {
  background: vermillion;
}
```

- [ ] **Step 2: Реализовать `SettingsPage.tsx`**

```tsx
// frontend/src/pages/SettingsPage.tsx
import { useEffect, useState } from "react";
import { bulkDeleteGames } from "../game/api";
import {
  type UserSettings,
  changePassword,
  getSettings,
  saveSettings,
} from "../settings.api";
import styles from "./SettingsPage.module.css";

type ConfirmKind = "delete-current" | "delete-finished" | "save-limit" | null;

export default function SettingsPage() {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [draft, setDraft] = useState<UserSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmKind>(null);

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwError, setPwError] = useState("");
  const [savingPw, setSavingPw] = useState(false);

  useEffect(() => {
    getSettings().then((s) => {
      setSettings(s);
      setDraft(s);
    });
  }, []);

  if (!settings || !draft) {
    return (
      <div className={styles.wrap}>
        <div className={styles.eyebrow}>Профиль</div>
        <h1 className={styles.title}>Настройки</h1>
      </div>
    );
  }

  const isDirty =
    draft.games_limit !== settings.games_limit ||
    draft.games_limit_enabled !== settings.games_limit_enabled ||
    draft.undo_enabled !== settings.undo_enabled ||
    draft.undo_limit !== settings.undo_limit ||
    draft.undo_after_game_end !== settings.undo_after_game_end;

  function handleSaveSettings() {
    if (
      draft!.games_limit_enabled &&
      draft!.games_limit < settings!.games_limit
    ) {
      setConfirm("save-limit");
    } else {
      doSaveSettings();
    }
  }

  function doSaveSettings() {
    setSavingSettings(true);
    saveSettings(draft!)
      .then((s) => {
        setSettings(s);
        setDraft(s);
      })
      .finally(() => setSavingSettings(false));
  }

  async function handleChangePw() {
    setPwError("");
    setSavingPw(true);
    try {
      await changePassword(curPw, newPw);
      setCurPw("");
      setNewPw("");
    } catch (e: unknown) {
      setPwError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setSavingPw(false);
    }
  }

  async function doBulkDelete(section: "current" | "finished") {
    await bulkDeleteGames(section);
    setConfirm(null);
  }

  const confirmText: Record<Exclude<ConfirmKind, null>, { title: string; body: string; action: () => void }> = {
    "delete-current": {
      title: "Удалить текущие партии",
      body: "Удалить все текущие партии? Это действие нельзя отменить.",
      action: () => doBulkDelete("current"),
    },
    "delete-finished": {
      title: "Удалить завершённые партии",
      body: "Удалить все завершённые партии? Это действие нельзя отменить.",
      action: () => doBulkDelete("finished"),
    },
    "save-limit": {
      title: "Уменьшение лимита",
      body: "Уменьшение лимита удалит старейшие партии сверх нового предела. Продолжить?",
      action: () => { setConfirm(null); doSaveSettings(); },
    },
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Профиль</div>
      <h1 className={styles.title}>Настройки</h1>

      {/* Откаты */}
      <div className={styles.sectionTitle}>Откаты</div>
      <div className={styles.settings}>
        <div className={styles.setrow}>
          <div>
            <div className={styles.setrowLabel}>Отмена ходов (undo)</div>
            <div className={styles.setrowDesc}>Разрешить откатывать ходы во время игры.</div>
          </div>
          <div
            className={draft.undo_enabled ? styles.toggleOn : styles.toggle}
            onClick={() => setDraft({ ...draft, undo_enabled: !draft.undo_enabled })}
            role="switch"
            aria-checked={draft.undo_enabled}
          />
        </div>

        {draft.undo_enabled && (
          <>
            <div className={styles.setrow}>
              <div>
                <div className={styles.setrowLabel}>Лимит откатов</div>
                <div className={styles.setrowDesc}>Сколько раз за партию можно отменить ход. ∞ — без ограничений.</div>
              </div>
              <div className={styles.stepper}>
                <button
                  className={styles.stepperBtn}
                  onClick={() =>
                    setDraft({ ...draft, undo_limit: draft.undo_limit === 1 ? null : draft.undo_limit !== null ? draft.undo_limit - 1 : null })
                  }
                >−</button>
                <div className={styles.stepperNum}>
                  {draft.undo_limit === null ? "∞" : draft.undo_limit}
                </div>
                <button
                  className={styles.stepperBtn}
                  onClick={() =>
                    setDraft({ ...draft, undo_limit: draft.undo_limit === null ? 1 : Math.min(999, draft.undo_limit + 1) })
                  }
                >+</button>
              </div>
            </div>

            <div className={styles.setrow}>
              <div>
                <div className={styles.setrowLabel}>Откат после конца партии</div>
                <div className={styles.setrowDesc}>Позволить вернуться в игру из завершённой партии.</div>
              </div>
              <div
                className={draft.undo_after_game_end ? styles.toggleOn : styles.toggle}
                onClick={() => setDraft({ ...draft, undo_after_game_end: !draft.undo_after_game_end })}
                role="switch"
                aria-checked={draft.undo_after_game_end}
              />
            </div>
          </>
        )}
      </div>

      {/* Управление партиями */}
      <div className={styles.sectionTitle}>Управление партиями</div>
      <div className={styles.settings}>
        <div className={styles.setrow}>
          <div>
            <div className={styles.setrowLabel}>Партий на раздел</div>
            <div className={styles.setrowDesc}>Верхний предел партий в каждом разделе (текущие / завершённые). 10–100.</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              className={draft.games_limit_enabled ? styles.toggleOn : styles.toggle}
              onClick={() => setDraft({ ...draft, games_limit_enabled: !draft.games_limit_enabled })}
              role="switch"
              aria-checked={draft.games_limit_enabled}
            />
            {draft.games_limit_enabled && (
              <div className={styles.stepper}>
                <button
                  className={styles.stepperBtn}
                  onClick={() => setDraft({ ...draft, games_limit: Math.max(10, draft.games_limit - 10) })}
                >−</button>
                <div className={styles.stepperNum}>{draft.games_limit}</div>
                <button
                  className={styles.stepperBtn}
                  onClick={() => setDraft({ ...draft, games_limit: Math.min(100, draft.games_limit + 10) })}
                >+</button>
              </div>
            )}
          </div>
        </div>
        <div className={styles.setrow}>
          <div>
            <div className={styles.setrowLabel}>Удалить текущие</div>
            <div className={styles.setrowDesc}>Стереть все незавершённые партии.</div>
          </div>
          <button className={styles.dangerRowBtn} onClick={() => setConfirm("delete-current")}>
            Удалить все
          </button>
        </div>
        <div className={styles.setrow}>
          <div>
            <div className={styles.setrowLabel}>Удалить завершённые</div>
            <div className={styles.setrowDesc}>Стереть все сыгранные партии.</div>
          </div>
          <button className={styles.dangerRowBtn} onClick={() => setConfirm("delete-finished")}>
            Удалить все
          </button>
        </div>
      </div>

      <button
        className={styles.saveBtn}
        disabled={!isDirty || savingSettings}
        onClick={handleSaveSettings}
      >
        {savingSettings ? "Сохранение…" : "Сохранить"}
      </button>

      {/* Сменить пароль */}
      <div className={styles.passwordBlock}>
        <div className={styles.sectionTitle}>Сменить пароль</div>
        <div className={styles.field}>
          <label>Текущий пароль</label>
          <input type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} />
        </div>
        <div className={styles.field}>
          <label>Новый пароль</label>
          <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
        </div>
        <p className={styles.hint}>После смены пароля другие устройства и вкладки будут отключены.</p>
        {pwError && <p className={styles.errMsg}>{pwError}</p>}
        <button
          className={styles.saveBtn}
          disabled={!curPw || !newPw || savingPw}
          onClick={handleChangePw}
        >
          {savingPw ? "Сохранение…" : "Обновить пароль"}
        </button>
      </div>

      {/* Диалоги подтверждения */}
      {confirm && (
        <div className={styles.overlay} onClick={() => setConfirm(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalTitle}>{confirmText[confirm].title}</div>
            <p className={styles.modalBody}>{confirmText[confirm].body}</p>
            <div className={styles.modalFooter}>
              <button className={styles.cancelBtn} onClick={() => setConfirm(null)}>Отмена</button>
              <button className={styles.dangerBtn} onClick={confirmText[confirm].action}>
                {confirm === "save-limit" ? "Продолжить" : "Удалить все"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Переписать `SettingsPage.test.tsx`**

```tsx
// frontend/src/pages/SettingsPage.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, it, expect, beforeEach } from "vitest";

// vi.mock поднимается до импортов — мокаем до загрузки компонента (паттерн UsersTab.test.tsx)
vi.mock("../settings.api", () => ({
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
  changePassword: vi.fn(),
}));

vi.mock("../game/api", () => ({
  bulkDeleteGames: vi.fn(),
}));

import SettingsPage from "./SettingsPage";
import * as settingsApi from "../settings.api";
import * as gameApi from "../game/api";

const defaultSettings = {
  games_limit: 50,
  games_limit_enabled: true,
  undo_enabled: true,
  undo_limit: null,
  undo_after_game_end: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(settingsApi.getSettings).mockResolvedValue({ ...defaultSettings });
  vi.mocked(settingsApi.saveSettings).mockResolvedValue({ ...defaultSettings });
  vi.mocked(settingsApi.changePassword).mockResolvedValue(undefined);
  vi.mocked(gameApi.bulkDeleteGames).mockResolvedValue(undefined);
});

it("отображает заголовок Настройки", async () => {
  render(<SettingsPage />);
  expect(await screen.findByRole("heading", { name: /Настройки/i })).toBeInTheDocument();
});

it("кнопка Сохранить disabled пока нет изменений", async () => {
  render(<SettingsPage />);
  const btn = await screen.findByRole("button", { name: /Сохранить/i });
  expect(btn).toBeDisabled();
});

it("кнопка Сохранить активируется при изменении toggle", async () => {
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  const toggle = screen.getAllByRole("switch")[0]; // undo toggle
  fireEvent.click(toggle);
  const btn = screen.getByRole("button", { name: /Сохранить/i });
  expect(btn).not.toBeDisabled();
});

it("диалог удаления открывается при клике на Удалить все", async () => {
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  const deleteBtn = screen.getAllByText("Удалить все")[0];
  fireEvent.click(deleteBtn);
  expect(screen.getByText(/Это действие нельзя отменить/i)).toBeInTheDocument();
});

it("подтверждение удаления вызывает bulkDeleteGames", async () => {
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  // Открыть диалог первой кнопкой «Удалить все»
  fireEvent.click(screen.getAllByText("Удалить все")[0]);
  // В модале появляется кнопка-подтверждение — берём последнюю (в оверлее), не строчную
  const confirmBtns = screen.getAllByRole("button", { name: /Удалить все/i });
  fireEvent.click(confirmBtns[confirmBtns.length - 1]);
  await waitFor(() => expect(gameApi.bulkDeleteGames).toHaveBeenCalledWith("current"));
});

it("ошибка 400 при смене пароля показывает errMsg", async () => {
  vi.spyOn(settingsApi, "changePassword").mockRejectedValue(new Error("Неверный текущий пароль"));
  render(<SettingsPage />);
  await screen.findByRole("heading", { name: /Настройки/i });
  fireEvent.change(screen.getByLabelText(/Текущий пароль/i), { target: { value: "wrong" } });
  fireEvent.change(screen.getByLabelText(/Новый пароль/i), { target: { value: "newpass123" } });
  fireEvent.click(screen.getByRole("button", { name: /Обновить пароль/i }));
  expect(await screen.findByText("Неверный текущий пароль")).toBeInTheDocument();
});

it("показывает предупреждение про другие устройства", async () => {
  render(<SettingsPage />);
  await screen.findByText(/другие устройства/i);
});
```

- [ ] **Step 4: TypeScript-проверка**

```bash
cd frontend
npx tsc --noEmit
```
Ожидание: 0 ошибок

- [ ] **Step 5: Прогнать тесты фронта**

```bash
cd frontend
npx vitest run --reporter=verbose
```
Ожидание: все PASSED

- [ ] **Step 6: Полный прогон бэкенда**

```bash
cd backend
uv run pytest -q
```
Ожидание: все PASSED

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx \
        frontend/src/pages/SettingsPage.module.css \
        frontend/src/pages/SettingsPage.test.tsx
git commit -m "feat(rj-xt2): экран Настройки — откаты, лимиты, пароль"
```
