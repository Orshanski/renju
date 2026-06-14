# Ретеншн партий — БЭКЕНД-срез (rj-as6) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (рекоменд.) или superpowers:executing-plans. Шаги — чекбоксы (`- [ ]`).

**Goal:** Бэкенд персонального ретеншна партий: три раздела (Текущие/Завершённые/Избранное), per-user лимиты по количеству с событийным вытеснением (без таймера), избранное вне лимита, лёгкий list-эндпоинт (summary-DTO), эндпоинты delete/favorite/unfavorite.

**Architecture:** Чистая логика (раздел партии + выбор кандидатов на вытеснение) — в `app/domain/retention.py` (без I/O, юнит-тесты). Модель: новые поля `Game.favorite`/`Game.finished_at` + таблица `user_settings` (лимиты, дефолты в БД). Сервис вешает вытеснение на точки создания/завершения партии и читает лимиты. Источник: `docs/superpowers/specs/2026-06-13-game-retention-design.md`.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy async / Alembic / pytest. БД SQLite.

**Фронт-срез (три раздела + действия + экран новой партии)** — ОТДЕЛЬНЫЙ план, после этого.

## Структура файлов

- Create: `backend/app/domain/retention.py` — чистые `Section`, `game_section`, `select_evictions`.
- Create: `backend/app/models/user_settings.py` — модель `UserSettings`.
- Create: `backend/alembic/versions/<rev>_game_retention.py` — миграция (autogenerate).
- Create: `backend/app/game/settings_repository.py` — репозиторий настроек (get-or-default/upsert).
- Modify: `backend/app/models/game.py` — поля `favorite`, `finished_at`.
- Modify: `backend/app/game/repository.py` — `delete`, листинг с новыми полями, `count` по разделу.
- Modify: `backend/app/game/service.py` — `finished_at` + вытеснение (создание/финиш), `favorite`/`unfavorite`/`delete_game`, чтение лимитов; вытеснение-на-смене-лимита как функция (триггер-эндпоинт — в rj-dix).
- Modify: `backend/app/game/dtos.py` — `GameSummaryDTO`.
- Modify: `backend/app/routers/games.py` — `DELETE /games/{id}`, `POST /games/{id}/favorite`, `/unfavorite`, лёгкий список по разделам.
- Modify: `backend/tests/conftest.py` — `import app.models.user_settings` в фикстурах `engine` (стр.30-31) и `app` (стр.55-56): тестовая БД строится `Base.metadata.create_all` с ПОИМЁННЫМ импортом моделей, иначе таблицы `user_settings` в ней не будет.
- Test: `tests/unit/test_retention.py`, `tests/unit/test_game_repository.py` (+ delete), `tests/unit/test_settings_repository.py`, `tests/unit/test_migration.py` (+ новые колонки/таблица), `tests/unit/test_game_service_contour.py`, `tests/api/test_games_endpoints.py`.

---

## Task 1: Домен — раздел партии + выбор вытеснения (чистое)

**Files:** Create `backend/app/domain/retention.py`; Test `backend/tests/unit/test_retention.py`.

- [ ] **Step 1: Failing-тесты**

```python
from datetime import datetime
from app.domain.retention import Section, game_section, Evictable, select_evictions


def test_section_priority_favorite_over_finished():
    assert game_section("finished_black", favorite=True) is Section.FAVORITE
    assert game_section("finished_draw", favorite=False) is Section.FINISHED
    assert game_section("awaiting_move", favorite=False) is Section.CURRENT
    assert game_section("opponent_thinking", favorite=False) is Section.CURRENT


def _e(i, t, c=None):
    return Evictable(id=i, sort_key=datetime(2026, 1, t), created_at=datetime(2026, 1, c or t))


def test_select_evictions_keeps_newest_n():
    items = [_e("a", 1), _e("b", 2), _e("c", 3)]
    assert select_evictions(items, limit=2) == ["a"]            # самый старый (по sort_key) выбывает
    assert select_evictions(items, limit=3) == []               # ровно лимит — никого
    assert select_evictions(items, limit=5) == []               # меньше лимита
    assert select_evictions(items, limit=1) == ["a", "b"]       # держим 1 → выбывают два старейших


def test_select_evictions_tiebreak_created_then_id():
    # равный sort_key → вторичный ключ created_at, затем id
    items = [_e("y", 5, c=2), _e("x", 5, c=1), _e("z", 5, c=1)]
    # держим 1 (новейший по (sort_key, created_at, id)): среди равных sort_key=5 «новейший» —
    # max по (created_at, id): created_at=2 (y). Выбывают x,z (created=1), порядок старейшие-первыми.
    assert select_evictions(items, limit=1) == ["x", "z"]
```

- [ ] **Step 2: Прогон — FAIL.** `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_retention.py -v`

- [ ] **Step 3: Реализация** `app/domain/retention.py`:

```python
"""Ретеншн партий: раздел партии и выбор кандидатов на вытеснение. Чистые функции, без I/O."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .values import GameStatus


class Section(StrEnum):
    CURRENT = "current"
    FINISHED = "finished"
    FAVORITE = "favorite"


def game_section(status: str, favorite: bool) -> Section:
    """Раздел партии по состоянию. Приоритет: favorite → finished → current."""
    if favorite:
        return Section.FAVORITE
    if GameStatus(status).is_finished:
        return Section.FINISHED
    return Section.CURRENT


@dataclass(frozen=True)
class Evictable:
    """Кандидат раздела на вытеснение. sort_key — время старшинства (finished_at для
    Завершённых, updated_at для Текущих); created_at/id — детерминированный тай-брейк."""
    id: str
    sort_key: datetime
    created_at: datetime


def select_evictions(items: Sequence[Evictable], limit: int) -> list[str]:
    """Держим новейшие `limit` партий раздела; возвращаем id на удаление (старейшие первыми).
    Старшинство: (sort_key, created_at, id) по возрастанию = старейшие сначала."""
    assert limit >= 1  # спека §3: лимит ≥ 1; «без лимита» — это не вызывать функцию (флаг enabled)
    ordered = sorted(items, key=lambda e: (e.sort_key, e.created_at, e.id))
    excess = len(ordered) - limit
    return [e.id for e in ordered[:excess]] if excess > 0 else []
```

- [ ] **Step 4: Прогон — PASS** + `uv run ruff check app tests && uv run ruff format app tests` + `uv run pyright app/domain/retention.py` (0 errors).

- [ ] **Step 5: Commit** — `cd /Users/alexey/code/Renju && git add backend/app/domain/retention.py backend/tests/unit/test_retention.py && git commit -m "feat(rj-as6): домен — раздел партии + выбор вытеснения (чистое)"`

---

## Task 2: Модель — поля Game + таблица user_settings + миграция

**Files:** Modify `backend/app/models/game.py`; Create `backend/app/models/user_settings.py`; миграция в `backend/alembic/versions/`.

- [ ] **Step 1: Поля `Game`** (`backend/app/models/game.py`) — добавить:

```python
    favorite: Mapped[bool] = mapped_column(default=False)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
```

- [ ] **Step 2: Модель `UserSettings`** (`backend/app/models/user_settings.py`):

```python
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
```

- [ ] **Step 3: Миграция (autogenerate).** `alembic/env.py` импортирует модели поимённо
(`import app.models.user`/`game`) — **добавить `import app.models.user_settings  # noqa: F401`**
рядом, иначе autogenerate не увидит таблицу. Новые поля `Game` подхватятся автоматически
(модель уже импортирована). Run:
`cd /Users/alexey/code/Renju/backend && uv run alembic revision --autogenerate -m "game_retention"`
Проверить сгенерированное (`alembic/versions/<rev>_game_retention.py`): `add_column('games','favorite')`, `add_column('games','finished_at')`, `create_table('user_settings', …)`, `down_revision='12c29568e213'`. Поправить если autogenerate напутал (server_default для `favorite`/лимитов на существующих строках — выставить `server_default=sa.text('0')`/`'10'`/`'50'`/`'1'` чтобы NOT NULL не падал на бэкфилле; либо nullable + бэкфилл).

- [ ] **Step 4: conftest + миграция-тест + применить.**
  (а) **conftest:** добавить `import app.models.user_settings  # noqa: F401` в `tests/conftest.py` в ОБЕ фикстуры — `engine` (рядом со стр.30-31) и `app` (рядом со стр.55-56). Тестовая БД строится `Base.metadata.create_all` с поимённым импортом, иначе `user_settings` в ней не появится → integration-тесты упадут на «no such table».
  (б) **миграция-тест:** дополнить `tests/unit/test_migration.py` (паттерн: subprocess `alembic upgrade head` + `inspect`): проверить, что в `games` есть колонки `favorite`/`finished_at`, и `"user_settings" in insp.get_table_names()`.
  (в) **применить/обратимость:** `cd /Users/alexey/code/Renju/backend && uv run alembic upgrade head`; затем `uv run alembic downgrade -1 && uv run alembic upgrade head`; затем `uv run pytest -q`.

- [ ] **Step 5: Commit** — `cd /Users/alexey/code/Renju && git add backend/app/models/game.py backend/app/models/user_settings.py backend/alembic/env.py backend/alembic/versions/ backend/tests/conftest.py backend/tests/unit/test_migration.py && git commit -m "feat(rj-as6): модель — Game.favorite/finished_at + user_settings + миграция"`

---

## Task 3: Репозитории — delete/листинг Game + настройки

**Files:** Modify `backend/app/game/repository.py`; Create `backend/app/game/settings_repository.py`; Test — дополнить `backend/tests/unit/test_game_repository.py` (delete; паттерн `_game()`/`test_sql_crud` с фикстурами `session`/`engine`) + создать `backend/tests/unit/test_settings_repository.py`.

- [ ] **Step 1: Failing-тесты** (InMemory-реализации + контракт): `delete(game_id)` убирает партию; `list_by_owner` отдаёт партии с полями `favorite`/`finished_at`; `SettingsRepository.get_or_default(user_id)` возвращает дефолты (10/50/вкл), если строки нет; `upsert` сохраняет.

```python
import pytest
from app.models.game import Game
from app.game.repository import InMemoryGameRepository
from app.game.settings_repository import InMemorySettingsRepository
from app.models.user_settings import DEFAULT_CURRENT_LIMIT, DEFAULT_FINISHED_LIMIT


async def test_game_repo_delete():
    r = InMemoryGameRepository()
    g = Game(id="g", owner_id=1, controllers={}, moves=[], status="awaiting_move",
             undo_count=0, forbidden_log={}, favorite=False, finished_at=None)
    await r.create(g)
    await r.delete("g")
    assert await r.get("g") is None


async def test_settings_get_or_default():
    r = InMemorySettingsRepository()
    s = await r.get_or_default(42)
    assert s.current_limit == DEFAULT_CURRENT_LIMIT and s.finished_limit == DEFAULT_FINISHED_LIMIT
    assert s.current_limit_enabled and s.finished_limit_enabled
```

- [ ] **Step 2: Прогон — FAIL.**

- [ ] **Step 3: Реализация.**
  - `repository.py`: в `GameRepository` (Protocol) + `SqlGameRepository` + `InMemoryGameRepository` добавить `async def delete(self, game_id: str) -> None`. (Sql: `await self._s.delete(obj); commit`.) `list_by_owner` уже отдаёт ORM-объекты — поля `favorite`/`finished_at` доступны, отдельный метод не нужен (фильтрацию по разделу делает сервис через `game_section`).
  - `settings_repository.py`: `SettingsRepository` Protocol (`get_or_default(user_id) -> UserSettings`, `upsert(settings) -> None`), `SqlSettingsRepository` (get по PK; нет → вернуть транзиентный `UserSettings(user_id=…)` с дефолтами, НЕ персистя), `InMemorySettingsRepository`.

- [ ] **Step 4: Прогон — PASS** + ruff + pyright.

- [ ] **Step 5: Commit** — `cd /Users/alexey/code/Renju && git add backend/app/game/repository.py backend/app/game/settings_repository.py backend/tests/unit/test_game_repository.py backend/tests/unit/test_settings_repository.py && git commit -m "feat(rj-as6): репозитории — Game.delete + настройки (get-or-default/upsert)"`

---

## Task 4: Сервис — finished_at + вытеснение + favorite/unfavorite/delete

**Files:** Modify `backend/app/game/service.py`; Test `backend/tests/unit/test_game_service_contour.py`.

- [ ] **Step 1: Failing-тесты** (контур с InMemory repo + fake adapter; владелец фиксирует игры):

```python
async def test_finish_sets_finished_at_and_evicts_over_limit():
    # finished_limit=2: при завершении 3-й — выбывает самая старая по finished_at
    ...  # создать 2 завершённые + 1 текущую, завершить текущую → finished=3 → одна удалена
    # assert finished_at проставлен; число Завершённых == 2

async def test_create_evicts_current_over_limit():
    # current_limit=2: создание 3-й Текущей удаляет самую давно-не-тронутую (updated_at)
    ...

async def test_favorite_only_finished_and_exempt_from_limit():
    # favorite на Завершённой → раздел favorite, вне лимита; favorite на Текущей → отказ
    ...

async def test_unfavorite_returns_to_finished_and_rechecks_limit():
    # из избранного → finished; finished_at не тронут; если > limit — вытеснение
    ...

async def test_delete_game_removes():
    ...
```

(Построения — по образцу существующих в файле: `_svc()`, явный `Game`, `svc._adapter`.
**Инъекция лимита:** `_svc()` после Task 4 принимает `settings_repo`; в тесте передать
`InMemorySettingsRepository`, куда заранее `upsert(UserSettings(user_id=owner, current_limit=2,
finished_limit=2))`. Тогда 3-я партия раздела вытесняет старейшую. Для `favorite`-отказа —
попытка пометить Текущую ждёт спец-ошибку/`MoveRejected`.)

- [ ] **Step 2: Прогон — FAIL.**

- [ ] **Step 3: Реализация** в `service.py`. `GameService.__init__` принимает `settings_repo` (новый параметр; роутер прокинет). Добавить:
  - `_set_finished_at(game)`: при переходе статуса в `is_finished` ставит `game.finished_at = now()` (UTC); при undo из finished — `game.finished_at = None` (в методе `undo`). Сбрасывать `favorite`? нет (undo из finished возможен только для не-избранных — избранные не на доске; но защитно: undo доступен по политике, favorite остаётся как есть — избранную не вытесняют, отдельный кейс не вводим).
  - В точках, где статус становится финальным (`advance` стр.106, `submit_move`/`_next_status` → финал), после установки статуса вызвать `_set_finished_at` + `await self._evict_finished(game.owner_id)`.
  - `create_game`: после создания — `await self._evict_current(owner_id)`.
  - `_evict_finished(owner_id)` / `_evict_current(owner_id)`: читают лимит из `settings_repo.get_or_default`; если `*_enabled` — собирают `Evictable` из партий раздела (`game_section`), зовут `select_evictions(items, limit)`, удаляют выбранные через `repo.delete` (партии-избранные и активный расчёт — §10 спеки: ручное/авто-удаление не трогает думающую — но §10 показал, что это не сценарий; для авто-вытеснения кандидат — давно не тронутая, активной не будет).
  - `enforce_limits(owner_id)` — общая функция «подрезать оба раздела до лимитов» (её вызовет будущий settings-update эндпоинт rj-dix; здесь — реализовать и юнит-тестом покрыть, без HTTP).
  - `favorite_game(game_id, user_id)`: только если партия Завершённая (`game_section == FINISHED`) → `game.favorite = True`; иначе `MoveRejected`/спец-ошибка. `unfavorite_game`: `favorite = False` → вернётся в Завершённые → `await self._evict_finished(owner)`.
  - `delete_game(game_id, user_id)`: проверка владения (`_load_owned`) → `repo.delete`. (Гашение engine-слота — забота реестра/idle-sweep, здесь только запись.)

- [ ] **Step 4: Прогон — PASS** (+ существующие контур-тесты зелёные) + ruff + pyright.

- [ ] **Step 5: Commit** — `git add backend/app/game/service.py backend/tests/unit/test_game_service_contour.py && git commit -m "feat(rj-as6): сервис — finished_at, вытеснение по лимитам, favorite/unfavorite/delete"`

---

## Task 5: Эндпоинты — delete/favorite/unfavorite + лёгкий список по разделам

**Files:** Modify `backend/app/routers/games.py`, `backend/app/game/dtos.py`; Test — дополнить `backend/tests/api/test_games_endpoints.py` (фикстуры `app`/`client`/`games_api`, `FakeAdapter`; НЕ `tests/integration/` — там live-движковые тесты).

- [ ] **Step 1: Failing-тесты** (HTTP): `DELETE /api/games/{id}` (204/200, владелец; 404 чужой); `POST /api/games/{id}/favorite` (Завершённую → ок; Текущую → 4xx); `/unfavorite`; лёгкий список отдаёт summary-DTO по разделам (без `winning_line`/`cursor`/полного состояния), сгруппированный/фильтруемый по `section`.

- [ ] **Step 2: Прогон — FAIL.**

- [ ] **Step 3: Реализация.**
  - `dtos.py`: `GameSummaryDTO(id, status, section, level_id|None, your_color|None, move_count, updated_at, finished_at|None, favorite)`.
  - `routers/games.py`: `_summary(game, user_id)` — без тяжёлых вычислений (переиспользует `_your_color`; `move_count=len(game.moves)`; `level_id` из controllers). Эндпоинты:
    - `DELETE /games/{game_id}` → `service.delete_game(game_id, user.user_id)`.
    - `POST /games/{game_id}/favorite` / `/unfavorite` → соответствующие методы сервиса, вернуть summary/state.
    - Лёгкий список: `GET /games?view=summary` (или новый `GET /games/summary`) → `[ _summary(g) for g in list_by_owner ]`, фронт группирует по `section` (или сервер отдаёт `{current:[], finished:[], favorite:[]}` — выбрать в реализации, summary в обоих случаях лёгкий). Текущий тяжёлый `GET /games` (полный `_state`) — оставить или пометить deprecated (фронт-срез перейдёт на summary); НЕ ломать существующие тесты на нём в этом срезе.
  - Прокинуть `settings_repo` в `_build_service` (создать `SqlSettingsRepository(session)`).

- [ ] **Step 4: Прогон — PASS** + весь набор `uv run pytest -q` + ruff + pyright.

- [ ] **Step 5: Commit** — `cd /Users/alexey/code/Renju && git add backend/app/routers/games.py backend/app/game/dtos.py backend/tests/api/test_games_endpoints.py && git commit -m "feat(rj-as6): эндпоинты delete/favorite/unfavorite + лёгкий список (summary-DTO)"`

---

## Ручное тестирование (Alexey, после Task 1–5)

Пересобрать/перезапустить сервер. Проверить: создание партий сверх лимита Текущих вытесняет старейшую; завершение сверх лимита Завершённых — старейшую по завершению; избранное не вытесняется; delete/favorite/unfavorite работают; список лёгкий (быстрый ответ).

## Самопроверка плана

- **Покрытие спеки:** §2 разделы (T1 `game_section`); §3 лимиты+дефолты в БД (T2 `user_settings`); §4 вытеснение событийно/до-лимита/тай-брейк (T1 `select_evictions` + T4 хуки); §4 смена лимита (T4 `enforce_limits`, триггер-эндпоинт — rj-dix); §5 избранное только из Завершённых/вне лимита (T4); §6 delete/favorite/unfavorite (T4+T5); §7 `finished_at`/favorite поля (T2), лёгкий list-эндпоинт summary-DTO (T5); §8 user_settings заводит эта фича (T2).
- **Вне scope (фронт-срез):** три раздела в UI, действия long-tap/правый-клик, экран новой партии — отдельный план.
- **Типы согласованы:** `Section`/`Evictable`/`select_evictions` (T1) ↔ сервис (T4); `UserSettings` поля (T2) ↔ `SettingsRepository` (T3) ↔ сервис (T4).
- **Открытое для плана-реализатора:** форма лёгкого списка (плоский `?view=summary` vs сгруппированный) — выбрать в T5, summary-DTO в любом случае лёгкий; server_default в миграции для бэкфилла существующих строк (T2 Step 3).
