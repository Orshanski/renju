# Game-Layer Modularity Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Вывести игровой слой бэка (`app/game/`, `app/routers/games.py`) и связанные мелочи на строгую модульную техбазу — типизированные границы, единый game-service, тонкий роутер, контроллер как единственный владелец своей формы — БЕЗ изменения поведения продукта.

**Architecture:** Серия из 7 узких поведенчески-нейтральных срезов, каждый самостоятельно зелёный и мержабельный, в порядке зависимостей. Источник истины поведения — существующие тесты (unit + integration против живого движка); рефактор обязан держать их зелёными. Где срез вводит новый чистый юнит — на него пишем юнит-тест первым (red→green). Где срез только перемещает/переименовывает — опора на существующий suite как характеризующий, плюс точечные тесты на новые публичные функции.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy async / pydantic / pytest (последовательно, не параллельно — shared Rapfi-процесс). Фронт-срез: React 18 / Vite / TypeScript / vitest + @testing-library/react ^16 (renderHook доступен) / MSW (`src/test/msw.ts`).

---

## Целевая структура (что куда переезжает)

```
app/
  domain/
    values.py          # ТОЛЬКО алфавит доски (Point, Color, GameStatus, BOARD_SIZE, MAX_MOVES, color_*) — без исключений
    errors.py          # НОВЫЙ: DomainError + Move/UndoRejected + reason-enum (вынос из values.py)        [Slice 5]
  game/
    controllers.py     # ЕДИНСТВЕННЫЙ владелец формы контроллера + типизированные аксессоры               [Slice 1]
    ports.py           # НОВЫЙ: Protocol'ы EngineAdapter / EventHub (GameRepository/SettingsRepository уже есть) [Slice 2]
    moves.py           # НОВЫЙ: apply_move/new_game/engine_move (вынос корневого app/game_service.py)     [Slice 3]
    service.py         # GameService — оркестрация хода/партии (ретеншн вынесен)
    retention_service.py # НОВЫЙ: RetentionService — вытеснение по лимитам (вынос логики из GameService)  [Slice 6]
    players.py         # типизированный adapter
    deps.py            # НОВЫЙ: FastAPI-зависимость build_game_service (вынос _build_service/_service)     [Slice 4]
    advance_manager.py # НОВЫЙ: AdvanceManager — фоновый advance + дедуп (вынос из роутера; владеет своим стейтом) [Slice 4]
    mappers.py         # НОВЫЙ: game→DTO (summary_dto/state_payload) поверх аксессоров контроллера         [Slice 4]
    dtos.py, event_hub.py, repository.py, settings_repository.py  # как есть
  routers/
    games.py           # ТОНКИЙ: только HTTP in/out, делегирует в deps/mappers/advance_manager
  game_service.py      # УДАЛЯЕТСЯ (переехал в game/moves.py)                                              [Slice 3]
frontend/src/game/
  useLevels.ts         # НОВЫЙ: общий хук id→имя уровня (вынос дубля из HomePage/GamePage)                 [Slice 7]
```

## Вне области этого плана (СОЗНАТЕЛЬНО — следующая фаза, фича настроек)

Считать **за scope этого плана** (НЕ реализовывать, НЕ предлагать как недоработку):

- **Снимок движковых параметров в партию** при создании (живой lookup `players.py:36` → заморозка силы/времени в `game.controllers`). Меняет ПОВЕДЕНИЕ («только новые партии») → фича engine-config.
- **Per-game выбор конфига реестром** (NNUE вкл/выкл через отдельный конфиг процесса; `registry.py:84` `config_path` из конструкторской константы → параметр операции). Тоже фича engine-config.
- **Эндпоинт `/admin/engine-config`, экран админки, NNUE-тумблер** (`rj-8py`, `rj-h1p`).

Рефактор лишь делает базу такой, чтобы это легло чисто. Логику реестра (`app/rapfi/registry.py`) НЕ трогаем (кроме того, что в Slice 2 он становится номинальной реализацией Protocol'а `EngineAdapter` — без правок кода реестра).

## Конвенции для исполнителя

- **Поведенчески-нейтрально.** Ни один HTTP-ответ, событие SSE, исход партии или строка протокола движка не меняется. Если пришлось ПОМЕНЯТЬ тест (не считая импортов/переименований/добавления no-op в фейк) — сигнал, что срез поехал в поведение: остановись, пересмотри.
- **Baseline перед каждым срезом:** из `backend/` — `uv run pytest -q` зелёный ДО начала среза.
- **pytest — последовательно** (один процесс Rapfi, shared state). Не `-n`.
- **Линт/формат** после правок: `uv run ruff check app tests && uv run ruff format app tests`.
- **Импорты — относительные в стиле файла** (`from ..domain...`, `from .controllers...`). Не вводить абсолютный стиль.
- **Коммит в конце КАЖДОГО среза.** Ветка одна на эпик: `chore/game-modularity-refactor`.
- Все команды ниже — из каталога `backend/` (кроме Slice 7 — из `frontend/`).

---

## Task 0: Ветка и baseline

- [ ] **Step 1: Ветка от чистого main**

Run: `git switch -c chore/game-modularity-refactor`
Expected: переключилось на новую ветку (main был чистый — проверено в начале сессии).

- [ ] **Step 2: Зелёный baseline**

Run: `cd backend && uv run pytest -q`
Expected: все PASS (unit + integration, ~6с). Красное ДО рефактора — стоп, спросить Alexey.

---

## Task 1 (Slice 1): Контроллер — единственный владелец своей формы

**Что и зачем:** форма контроллера (`{"kind":"engine","level_id":...}` / `{"kind":"user","user_id":...}`) читается сырым dict-доступом в `routers/games.py` в 4 хелперах: `_public_controllers` (78-86), `_your_color` (89-93), `_engine_level_id` (96-102), `_engine_level_tag` (291-297). Их зовут `_summary` (110-111), `_state` (134-135), `enter` (310). Стягиваем чтение формы за аксессоры в `controllers.py`.

**Files:**
- Modify: `backend/app/game/controllers.py` (добавить аксессоры)
- Modify: `backend/app/routers/games.py` (удалить 4 хелпера; `_summary`/`_state`/`enter` зовут аксессоры)
- Test: `backend/tests/unit/test_controllers.py` (новый)

- [ ] **Step 1: Падающий тест на аксессоры**

Создать `backend/tests/unit/test_controllers.py`:

```python
from app.game.controllers import (
    engine_level_id,
    engine_level_tag,
    public_view,
    user_side,
)

# Реальная форма: ключ стороны = Color.value ("black"/"white"), см. service.py:141-143.
BLACK_HUMAN = {"black": {"kind": "user", "user_id": 7}, "white": {"kind": "engine", "level_id": "master"}}
BOTH_HUMAN = {"black": {"kind": "user", "user_id": 7}, "white": {"kind": "user", "user_id": 9}}


def test_engine_level_id_returns_level():
    assert engine_level_id(BLACK_HUMAN) == "master"


def test_engine_level_id_none_when_no_engine():
    assert engine_level_id(BOTH_HUMAN) is None


def test_engine_level_tag_returns_level_or_dash():
    assert engine_level_tag(BLACK_HUMAN) == "master"
    assert engine_level_tag(BOTH_HUMAN) == "-"


def test_user_side_finds_owner():
    assert user_side(BLACK_HUMAN, 7) == "black"
    assert user_side(BLACK_HUMAN, 999) is None


def test_public_view_hides_other_user_id_keeps_engine_level():
    assert public_view(BLACK_HUMAN) == {
        "black": {"kind": "user"},
        "white": {"kind": "engine", "levelId": "master"},
    }
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/unit/test_controllers.py -q`
Expected: FAIL (ImportError: cannot import name 'engine_level_id').

- [ ] **Step 3: Добавить аксессоры в `controllers.py`**

Дописать в `backend/app/game/controllers.py` (после существующих `controller_to_json`/`controller_from_json`):

```python
def _engines(controllers: dict) -> list[Engine]:
    out: list[Engine] = []
    for c in controllers.values():
        ctl = controller_from_json(c)
        if isinstance(ctl, Engine):
            out.append(ctl)
    return out


def engine_level_id(controllers: dict) -> str | None:
    """level_id engine-оппонента; None если engine-стороны нет или это плейсхолдер '-'."""
    for eng in _engines(controllers):
        return eng.level_id if eng.level_id != "-" else None
    return None


def engine_level_tag(controllers: dict) -> str:
    """level_id engine-оппонента для логов реестра; '-' если engine-стороны нет."""
    for eng in _engines(controllers):
        return eng.level_id
    return "-"


def user_side(controllers: dict, user_id: int) -> str | None:
    """Сторона ('black'/'white'), которой управляет данный пользователь; None если его нет."""
    for side, c in controllers.items():
        ctl = controller_from_json(c)
        if isinstance(ctl, User) and ctl.user_id == user_id:
            return side
    return None


def public_view(controllers: dict) -> dict:
    """Публичная форма для фронта: id чужого игрока не светим, у движка отдаём levelId."""
    out: dict = {}
    for side, c in controllers.items():
        ctl = controller_from_json(c)
        out[side] = (
            {"kind": "engine", "levelId": ctl.level_id}
            if isinstance(ctl, Engine)
            else {"kind": "user"}
        )
    return out
```

- [ ] **Step 4: Тест аксессоров зелёный**

Run: `cd backend && uv run pytest tests/unit/test_controllers.py -q`
Expected: PASS.

- [ ] **Step 5: Заменить хелперы роутера на аксессоры**

В `backend/app/routers/games.py`:
- Удалить функции `_public_controllers` (78-86), `_your_color` (89-93), `_engine_level_id` (96-102), `_engine_level_tag` (291-297).
- В импортах добавить: `from ..game.controllers import engine_level_id, engine_level_tag, public_view, user_side`.
- В `_summary` (105-121): `level_id=_engine_level_id(game.controllers)` → `engine_level_id(...)`; `your_color=_your_color(game.controllers, user_id)` → `user_side(...)`.
- В `_state` (124-142): `_public_controllers(game.controllers)` → `public_view(...)`; `_your_color(game.controllers, user_id)` → `user_side(...)`.
- В `enter` (310): `_engine_level_tag(game.controllers)` → `engine_level_tag(...)`.

- [ ] **Step 6: Полный suite + линт**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format app tests`
Expected: всё PASS, формат без диффов. Сторожа: `tests/api/test_games_endpoints.py` (публичная форма/your_color/summary не изменились).

- [ ] **Step 7: Commit**

```bash
git add backend/app/game/controllers.py backend/app/routers/games.py backend/tests/unit/test_controllers.py
git commit -m "refactor(rj): контроллер — единственный владелец формы (аксессоры вместо сырого dict в роутере)"
```

---

## Task 2 (Slice 2): Типизированные границы (Protocol'ы) + убрать getattr

**Что и зачем:** `GameService.__init__` (`service.py:44`) принимает `repo`/`hub`/`adapter` без типа (`settings_repo` уже типизирован `SettingsRepository`); `service.py:279` проверяет метод через `getattr(self._adapter, "sync_after_undo", None)`. Вводим Protocol'ы для границ.

**Точные сигнатуры адаптера (из `registry.py`):**
- `compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-") -> Point` (`registry.py:91`; `allowed_zone: frozenset[Point] | None` — позиционно-именованный ДО `*`).
- `forbidden_points(self, game_id, moves, *, level_tag="-") -> list[Point]` (`registry.py:132`).
- `sync_after_undo(self, game_id, moves, *, level_tag="-") -> None` (`registry.py:154`).

`mark_present`/`mark_absent` (`registry.py:240,244`) зовёт роутер напрямую (`games.py:310,325`) — это НЕ часть игрового Protocol'а (роутер-сторона), их не включаем. В `registry.py:41` уже есть Protocol `_EngineProc` — это интерфейс ПРОЦЕССА (RapfiProcess), не реестра; конфликта нет.

**Files:**
- Create: `backend/app/game/ports.py`
- Modify: `backend/app/game/service.py:44,279-281`, `backend/app/game/players.py:22,32`
- Modify: `backend/tests/conftest.py:82-111` (`_FakeAdapter` ← добавить `sync_after_undo`); проверить прочие фейк-адаптеры
- Test: `backend/tests/unit/test_ports.py` (новый)

- [ ] **Step 1: Падающий тест соответствия протоколу**

Создать `backend/tests/unit/test_ports.py`:

```python
from app.game.event_hub import InMemoryEventHub
from app.rapfi.registry import EngineRegistry


def test_registry_has_engine_adapter_methods():
    for name in ("compute_move", "forbidden_points", "sync_after_undo"):
        assert hasattr(EngineRegistry, name), name


def test_inmemory_hub_has_event_hub_methods():
    for name in ("publish", "cursor", "subscribe"):
        assert hasattr(InMemoryEventHub, name), name
```

(`from app.game.ports import EngineAdapter, EventHub` НЕ добавляем в тест — Protocol без `runtime_checkable` не используется в isinstance; тест лишь стережёт набор методов реальных реализаций.)

- [ ] **Step 2: Запустить — проходит на set-методов, но ports.py ещё нет → создаём его**

Run: `cd backend && uv run pytest tests/unit/test_ports.py -q`
Expected: PASS (тест не импортирует ports). Это baseline; ports.py создаём в Step 3 как контракт для аннотаций.

- [ ] **Step 3: Создать `ports.py`**

Создать `backend/app/game/ports.py`:

```python
"""Порты игрового слоя: что игровой слой ТРЕБУЕТ от инфраструктуры (§4.9).

Контракты объявлены на стороне потребителя (игровой слой); реализуют их
EngineRegistry (адаптер движка) и InMemoryEventHub (шина). Делает их подменяемыми
и убирает утиную типизацию (getattr) в сервисе. Сигнатуры зеркалят registry.py."""

from collections.abc import AsyncGenerator, Sequence
from typing import Protocol

from ..domain.engine_params import EngineParams
from ..domain.values import Point


class EngineAdapter(Protocol):
    async def compute_move(
        self,
        game_id: str,
        moves: Sequence[Point],
        params: EngineParams,
        allowed_zone: frozenset[Point] | None = None,
        *,
        level_tag: str = "-",
    ) -> Point: ...

    async def forbidden_points(
        self, game_id: str, moves: Sequence[Point], *, level_tag: str = "-"
    ) -> list[Point]: ...

    async def sync_after_undo(
        self, game_id: str, moves: Sequence[Point], *, level_tag: str = "-"
    ) -> None: ...


class EventHub(Protocol):
    def publish(self, game_id: str, type_: str, payload: dict) -> int: ...
    def cursor(self, game_id: str) -> int: ...
    def subscribe(
        self, game_id: str, since: int, idle_timeout: float | None = None
    ) -> AsyncGenerator[dict]: ...
```

- [ ] **Step 4: Проаннотировать потребителей и убрать getattr**

`backend/app/game/service.py`:
- Импорт: `from .ports import EngineAdapter, EventHub`.
- `__init__` (44): `adapter: EngineAdapter`, `hub: EventHub`. (`repo` можно типизировать `GameRepository` из `.repository`; `settings_repo` уже `SettingsRepository`; `levels: dict` оставить.)
- Строки 279-281: заменить
  ```python
  sync_after_undo = getattr(self._adapter, "sync_after_undo", None)
  if sync_after_undo is not None:
      await sync_after_undo(game.id, new_moves, level_tag="-")
  ```
  на:
  ```python
  await self._adapter.sync_after_undo(game.id, new_moves, level_tag="-")
  ```

`backend/app/game/players.py`:
- Импорт: `from .ports import EngineAdapter` (и `from ..domain.engine_params import EngineParams`, если ещё нет).
- `EnginePlayer.__init__(self, adapter: EngineAdapter, params: EngineParams, game_id: str, level_tag: str = "-")`.
- `make_player(ctl: Controller, adapter: EngineAdapter, levels: dict, game_id: str) -> Player`.

- [ ] **Step 5: Фейк-адаптеры обязаны иметь sync_after_undo**

В `backend/tests/conftest.py` класс `_FakeAdapter` (82-111) дописать метод (он сейчас ОТСУТСТВУЕТ — прямой вызов из Step 4 иначе AttributeError):

```python
    async def sync_after_undo(self, game_id, moves, *, level_tag="-"):
        pass
```

**Обязателен метод ТОЛЬКО `conftest._FakeAdapter`** — это единственный фейк, который реально проходит через `GameService.undo` (его гоняет `tests/api/test_games_endpoints.py` undo-сценарий). Прочие фейки НЕ трогать без нужды:
- `tests/unit/test_game_service_contour.py:7-21` (`FakeAdapter`) — УЖЕ имеет `sync_after_undo` (стр. 19-20).
- `tests/unit/test_game_service.py`, `tests/unit/test_players.py` — их фейки в undo-путь НЕ заходят (используются в `engine_move`/`make_player`-тестах) → no-op добавлять НЕ нужно. Добавить ТОЛЬКО если pyright ругнётся на них как на `EngineAdapter` (т.е. если фейк передаётся в `GameService(adapter=...)` с аннотацией). Лишние правки тестов размывают сигнал «правка теста = поехали в поведение» (конвенция плана).

Свериться: `cd backend && grep -rln "async def compute_move" tests`.

- [ ] **Step 6: Полный suite + линт + pyright (ОБЯЗАТЕЛЬНО)**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run pyright app/game`
Expected: PASS (особенно undo-пути: `tests/api/test_games_endpoints.py::test_move_then_undo`, `tests/unit/test_game_service*`). `pyright app/game` без новых ошибок — порты вводятся именно ради типизации границ, без type-checker они декоративны (scope — `app/game`, чтобы не цеплять pre-existing pyright-ошибки в тестах реестра, rj-dd7).

- [ ] **Step 7: Commit**

```bash
git add backend/app/game/ports.py backend/app/game/service.py backend/app/game/players.py backend/tests/
git commit -m "refactor(rj): типизированные порты EngineAdapter/EventHub; убрать getattr-утиную типизацию"
```

---

## Task 3 (Slice 3): Один game-service вместо двух однофамильцев

**Что и зачем:** `app/game_service.py` (корень: `apply_move`/`engine_move`/`new_game`) и `app/game/service.py` (класс `GameService`) — два модуля с почти одним именем. Пакет `game/` импортирует из корневого однофамильца (`players.py:5`, `service.py:20`). Переносим фасадные функции в `game/moves.py`, корневой файл удаляем.

**Files:**
- Create: `backend/app/game/moves.py` (содержимое бывшего `game_service.py`)
- Delete: `backend/app/game_service.py`
- Modify: `backend/app/game/players.py:5`, `backend/app/game/service.py:20`, `backend/app/domain/opening.py:11` (комментарий)
- Modify: тест-импортёры корневого модуля (найти grep'ом)

- [ ] **Step 1: Найти потребителей корневого модуля**

Run: `cd backend && grep -rn "game_service" app tests --include='*.py' | grep -v "game/service\|game/moves"`
Expected: импорты `from .game_service / from ..game_service / app.game_service` + комментарий `opening.py:11`. Зафиксировать список. NB: фильтр `-v "game/service"` СКРЫВАЕТ из вывода `app/game/service.py:20` (`from ..game_service import apply_move`) — он явно прописан в Step 3, не потерять.

- [ ] **Step 2: Создать `game/moves.py` копией `game_service.py`**

Скопировать содержимое `backend/app/game_service.py` в новый `backend/app/game/moves.py`. Поправить относительные импорты на уровень пакета `game/` (было из корня `app/` через `.domain`, станет `..domain`):
- `from .domain.engine_params import EngineParams` → `from ..domain.engine_params import EngineParams`
- `from .domain.game import validate_move` → `from ..domain.game import validate_move`
- `from .domain.opening import CENTER, opening_zone` → `from ..domain.opening import CENTER, opening_zone`
- `from .domain.rules import outcome_after` → `from ..domain.rules import outcome_after`
- `from .domain.values import MoveRejected, MoveRejectReason, Point` → `from ..domain.values import MoveRejected, MoveRejectReason, Point`

(NB: `MoveRejected`/`MoveRejectReason` позже переедут в `domain.errors` — Slice 5 поймает этот файл своим grep'ом.)
В докстринге шапки убрать строку «дозреет до game-service (тикет rj-8sc — очередь)» — дозрело.

- [ ] **Step 3: Переключить потребителей**

- `backend/app/game/players.py:5`: `from ..game_service import engine_move` → `from .moves import engine_move`.
- `backend/app/game/service.py:20`: `from ..game_service import apply_move` → `from .moves import apply_move`.
- Тест-импорты из Step 1: `app.game_service` → `app.game.moves`.
- `backend/app/domain/opening.py:11`: комментарий `game_service.new_game` → `game.moves.new_game`.

- [ ] **Step 4: Удалить корневой модуль**

Run: `cd backend && rm app/game_service.py`

- [ ] **Step 5: Полный suite + линт**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests`
Expected: PASS. ImportError → остался непереключённый потребитель (вернуться к Step 1).

- [ ] **Step 6: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "refactor(rj): свести двойной game-service — фасад хода переехал в app/game/moves.py"
```

---

## Task 4 (Slice 4): Тонкий роутер — DI-зависимость, маппинг DTO, AdvanceManager

**Что и зачем:** `routers/games.py` делает не-HTTP вещи: ручная сборка сервиса (`_build_service` 30-38, обёртка `_service` 41-42), оркестрация фона (`schedule_advance` 45-75 + `app.state.advancing`/`app.state.bg_tasks`), маппинг game→DTO (`_summary` 105, `_state` 124). Выносим каждую в свой модуль. `schedule_advance` зовётся в 4 местах: `create_game:167`, `get_game:238`, `move:267`, `events:340`.

**Files:**
- Create: `backend/app/game/deps.py`, `backend/app/game/mappers.py`, `backend/app/game/advance_manager.py`
- Modify: `backend/app/routers/games.py` (тонкий), `backend/app/app_factory.py:67-78` (AdvanceManager на app.state; убрать сырые advancing/bg_tasks)
- Test: `backend/tests/unit/test_advance_manager.py` (новый)

- [ ] **Step 1: Падающий тест дедупа AdvanceManager**

Создать `backend/tests/unit/test_advance_manager.py`:

```python
import asyncio

import pytest

from app.game.advance_manager import AdvanceManager


@pytest.mark.asyncio
async def test_dedup_skips_second_schedule_while_running():
    started: list[str] = []
    release = asyncio.Event()

    async def runner(game_id: str):
        started.append(game_id)
        await release.wait()

    mgr = AdvanceManager(runner)
    mgr.schedule("g1")
    mgr.schedule("g1")  # пока первый крутится — дубль не плодим
    await asyncio.sleep(0)
    assert started == ["g1"]
    release.set()
    await mgr.drain()


@pytest.mark.asyncio
async def test_after_completion_can_schedule_again():
    started: list[str] = []

    async def runner(game_id: str):
        started.append(game_id)

    mgr = AdvanceManager(runner)
    mgr.schedule("g1")
    await mgr.drain()
    mgr.schedule("g1")
    await mgr.drain()
    assert started == ["g1", "g1"]
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/unit/test_advance_manager.py -q`
Expected: FAIL (ModuleNotFoundError: app.game.advance_manager).

- [ ] **Step 3: Реализовать AdvanceManager**

Создать `backend/app/game/advance_manager.py` (семантика из `games.py:45-75`, но стейт внутри):

```python
"""Фоновый advance партии с дедупом по game_id. Владеет своим стейтом
(набор активных game_id + ссылки на таски), а не размазывает по app.state.

runner(game_id) — корутина, прогоняющая advance в СВОЕЙ сессии. Конкретный runner
(с sessionmaker/service и гейтом adapter-is-None) собирает app_factory."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger("renju.advance")


class AdvanceManager:
    def __init__(self, runner: Callable[[str], Awaitable[None]]):
        self._runner = runner
        self._active: set[str] = set()  # game_id с активным прогоном (дедуп)
        self._tasks: set[asyncio.Task] = set()  # ссылки, чтобы GC не оборвал

    def schedule(self, game_id: str) -> None:
        if game_id in self._active:  # уже крутится — не плодим дубль
            return
        self._active.add(game_id)
        task = asyncio.create_task(self._run(game_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, game_id: str) -> None:
        try:
            await self._runner(game_id)
        except Exception:
            logger.exception("background advance failed: game=%s", game_id)
        finally:
            self._active.discard(game_id)

    async def drain(self) -> None:
        """Дождаться ЕСТЕСТВЕННОГО завершения активных прогонов (для тестов)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """Shutdown: ОТМЕНИТЬ незавершённые прогоны и дождаться сворачивания.
        Сохраняет семантику прежнего lifespan (app_factory.py:72-75: t.cancel()
        для каждой bg-задачи, затем gather) — НЕ ждём естественного завершения."""
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
```

- [ ] **Step 4: Тест менеджера зелёный**

Run: `cd backend && uv run pytest tests/unit/test_advance_manager.py -q`
Expected: PASS.

- [ ] **Step 5: Вынести маппинг DTO в `mappers.py`**

Создать `backend/app/game/mappers.py`. Перенести тела `_summary` (games.py:105-121) и `_state` (games.py:124-142):

```python
from ..domain.retention import game_section
from ..domain.rules import winning_line
from ..domain.values import GameStatus
from .controllers import engine_level_id, public_view, user_side
from .dtos import GameSummaryDTO


def summary_dto(game, user_id: int) -> GameSummaryDTO:
    return GameSummaryDTO(
        id=game.id,
        status=game.status,
        section=game_section(game.status, game.favorite).value,
        level_id=engine_level_id(game.controllers),
        your_color=user_side(game.controllers, user_id),
        move_count=len(game.moves),
        moves=game.moves,
        favorite=game.favorite,
        updated_at=game.updated_at,
        finished_at=game.finished_at,
    )


def state_payload(game, user_id: int, hub) -> dict:
    fb = game.forbidden_log.get(str(len(game.moves)), [])
    wl = (
        winning_line([tuple(m) for m in game.moves])
        if GameStatus(game.status).is_finished
        else None
    )
    return {
        "id": game.id,
        "owner_id": game.owner_id,
        "controllers": public_view(game.controllers),
        "your_color": user_side(game.controllers, user_id),
        "status": game.status,
        "moves": game.moves,
        "undo_count": game.undo_count,
        "cursor": hub.cursor(game.id),
        "forbidden": fb,
        "winning_line": [list(p) for p in wl] if wl is not None else None,
    }
```

(`hub` оставляем нетипизированным параметром здесь — он уже описан Protocol'ом `EventHub`, но мэппер технически нуждается только в `.cursor`; типизировать `hub: EventHub` по желанию.)

- [ ] **Step 6: Вынести сборку сервиса в `deps.py`**

Создать `backend/app/game/deps.py` (перенос `_build_service` games.py:30-38, как FastAPI-зависимость; пути импортов точные):

```python
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.deps import get_session
from .repository import SqlGameRepository
from .service import GameService
from .settings_repository import SqlSettingsRepository


def make_game_service(app, session: AsyncSession) -> GameService:
    """Сборка GameService на ЯВНОЙ сессии (переиспользуется в DI и в SSE-стриме,
    который держит свою короткую сессию). Перенос тела games.py:30-38."""
    levels = {lid: lv.params for lid, lv in app.state.levels.items()}
    return GameService(
        repo=SqlGameRepository(session),
        hub=app.state.event_hub,
        adapter=app.state.adapter,
        levels=levels,
        settings_repo=SqlSettingsRepository(session),
    )


def build_game_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GameService:
    """FastAPI-зависимость: тонкая обёртка над make_game_service на request-сессии."""
    return make_game_service(request.app, session)
```

В роутере заменить `svc = _service(request, session)` / `_build_service(...)`:
- В обычных эндпоинтах — на DI: параметр `service: Annotated[GameService, Depends(build_game_service)]`, звать `service.<метод>`. Где `session` использовался ТОЛЬКО для `_service` — убрать прямой `session`-параметр (его тянет `build_game_service`).
- В `events` (games.py:329-357) — НЕ через DI. **Сигнатуру `events(game_id, request, since=0)` НЕ менять** (её зовёт напрямую как функцию `tests/api/test_games_sse.py`, минуя FastAPI). Внутри `async with sm() as s0` заменить `_service(request, s0)` (games.py:338) на `make_game_service(request.app, s0)`. SSE остаётся на короткой сессии s0, auth — там же; сессия не держится весь стрим.

- [ ] **Step 7: AdvanceManager в app_factory + тонкий роутер**

`backend/app/app_factory.py` (lifespan, район 60-78):
- Определить `runner(game_id)` (тело из `games.py:61-71` + гейт `adapter is None` из `games.py:52-56`): если `app.state.adapter is None` → `logger.warning(...)`, return; иначе `async with app.state.sessionmaker() as s: svc = make_game_service(app, s); game = await svc.load(game_id); if game: await svc.advance(game)`.
- `app.state.advance = AdvanceManager(runner)`.
- Убрать `app.state.bg_tasks = set()` (68) и `app.state.advancing = set()` (69) — стейт теперь в менеджере.
- Shutdown (71-78): заменить ручной сбор+`cancel`+`gather` по `bg_tasks` на `await app.state.advance.aclose()` ПЕРЕД отменой sweep и dispose. **Именно `aclose()` (cancel→gather), НЕ `drain()`** — сохраняем прежнюю семантику: незавершённый advance ОТМЕНЯЕТСЯ, а не дожидается (иначе shutdown подвиснет на расчёте движка; инвариант registry.py:290 «close зовётся после отмены bg-advance» сохраняется).

`backend/app/routers/games.py`:
- Удалить `_build_service`, `_service`, `schedule_advance`, `_summary`, `_state`.
- Импорты: `from ..game.mappers import summary_dto, state_payload`, `from ..game.deps import build_game_service` (+ helper для events).
- Где было `schedule_advance(request.app, game_id)` (create_game/get_game/move/events) → `request.app.state.advance.schedule(game_id)`. Гейт `adapter is None` теперь в runner'е — на observable-поведение не влияет (advance не происходит в обоих случаях).
- `_summary(g, uid)` → `summary_dto(g, uid)`; `_state(g, uid, hub)` → `state_payload(g, uid, hub)`.

- [ ] **Step 8: Полный suite (вкл. фон/SSE) + линт**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run ruff format app tests`
Expected: PASS. Сторожа: `tests/api/test_games_endpoints.py`, `tests/api/test_games_sse.py`, `tests/integration/test_games_live.py` (фон, SSE, DTO не изменились).

- [ ] **Step 9: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "refactor(rj): тонкий роутер игр — DI-deps, mappers, AdvanceManager (инкапсуляция фон-стейта)"
```

---

## Task 5 (Slice 5, мелочь): Доменные исключения — отдельный модуль

**Что и зачем:** `domain/values.py:42-73` смешивает алфавит доски и протокол ошибок (`DomainError`, `MoveRejectReason`, `MoveRejected`, `UndoRejectReason`, `UndoRejected`). Разносим исключения → `domain/errors.py`. В `values.py` остаются `BOARD_SIZE`, `MAX_MOVES`, `Point`, `Color`, `GameStatus`, `color_of_move`, `color_to_move`.

**Files:**
- Create: `backend/app/domain/errors.py`
- Modify: `backend/app/domain/values.py` (убрать строки 42-73)
- Modify: импортёры `MoveRejected/MoveRejectReason/UndoRejected/UndoRejectReason/DomainError` из `domain.values`
- Modify: `backend/tests/unit/test_values.py` (возможно выделить `test_errors.py`)

- [ ] **Step 1: Найти импортёров**

Run: `cd backend && grep -rn "MoveRejected\|MoveRejectReason\|UndoRejected\|UndoRejectReason\|DomainError" app tests --include='*.py'`
Expected (список НЕ-исчерпывающий, ориентир — фактический вывод grep'а): `routers/games.py:16` (`from ..domain.values import GameStatus, MoveRejected, UndoRejected` — СМЕШАННЫЙ с GameStatus → разделить); `app/error_handlers.py:34` (`from .domain.values import MoveRejected, MoveRejectReason, UndoRejected, UndoRejectReason` — ФУНКЦИЯ-локальный импорт внутри `register_error_handlers`, тоже переключить на `.domain.errors`); `domain/game.py:5-13` (СМЕШАННЫЙ с BOARD_SIZE/Color/Point); `domain/undo.py:5` (СМЕШАННЫЙ с GameStatus); `game/moves.py`, `game/service.py`, тесты. Step 4 («Везде из Step 1») закрывает все — фиксируем по фактическому grep'у, не по этому списку.

- [ ] **Step 2: Создать `domain/errors.py`**

Перенести из `values.py` (строки 42-73) ровно: `class DomainError(Exception)`, `class MoveRejectReason(StrEnum)`, `class MoveRejected(DomainError)`, `class UndoRejectReason(StrEnum)`, `class UndoRejected(DomainError)`. Шапка модуля — `"""Доменные ошибки рэндзю. Без I/O."""`. Импорт `from enum import StrEnum`.

- [ ] **Step 3: Убрать их из `values.py`** — удалить строки 42-73. (`values.py` сам эти классы не использует — проверить, что после удаления нет внутренних ссылок.)

- [ ] **Step 4: Переключить импортёров**

Везде из Step 1: импорт этих имён из `...domain.values` → `...domain.errors`. Смешанные импорты (как `games.py:16`) разделить: `from ..domain.values import GameStatus` + `from ..domain.errors import MoveRejected, UndoRejected`.

- [ ] **Step 5: Полный suite + линт**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "refactor(rj): доменные исключения → domain/errors.py (values.py — только алфавит доски)"
```

---

## Task 6 (Slice 6, мелочь): RetentionService — вынос вытеснения из GameService

**Что и зачем:** `GameService` совмещает ход и ретеншн: `_evict_current` (94-113), `_evict_finished` (115-130), `enforce_limits` (132-136). Внутренние вызовы: `create_game:158`, `advance:173`, `submit_move:249`, `unfavorite_game:311`. Публичный `enforce_limits` сейчас зовётся ТОЛЬКО из теста `tests/unit/test_game_service_contour.py:763` (settings-эндпоинта ещё нет — `rj-dix`). Выносим ЛОГИКУ в `RetentionService`; `GameService` делегирует (включая тонкий `enforce_limits`, чтобы тест остался валиден).

**Files:**
- Create: `backend/app/game/retention_service.py`, `backend/app/game/_time.py` (вынос `_now`)
- Modify: `backend/app/game/service.py` (убрать тела evict + `_now`; строить RetentionService ВНУТРИ из своих repo+settings_repo, делегировать; `_now` ← из `._time`)
- Test: `backend/tests/unit/test_retention_service.py` (новый)

NB: конструктор `GameService.__init__(repo, hub, adapter, levels, settings_repo)` НЕ меняем — RetentionService собирается внутри. Иначе пришлось бы править `_svc` (`test_game_service_contour.py:23-30`) и `build_game_service`/`events`-сборку. Внутренняя сборка = меньше churn и поведенчески-нейтрально.

- [ ] **Step 1: Падающий тест оркестрации**

Создать `backend/tests/unit/test_retention_service.py` (на `InMemoryGameRepository` + `InMemorySettingsRepository` из `app.game.settings_repository`, `UserSettings` из `app.models.user_settings`). Кейс: 2 текущие партии разного `updated_at`, `current_limit=1`/`current_limit_enabled=True` → `enforce_limits(owner)` → осталась свежая. **Образец сборки Game + UserSettings + repo — точь-в-точь `test_game_service_contour.py:705-763`** (там `Game(id, owner_id, controllers={"black":{"kind":"user","user_id":1},"white":{"kind":"engine","level_id":"master"}}, moves=[[7,7]], status="awaiting_move", undo_count=0, forbidden_log={}, favorite=False, finished_at=None, created_at=, updated_at=)` + `InMemorySettingsRepository().upsert(UserSettings(...))`). `tests/unit/test_retention.py` — образец для ДОМЕННОЙ `select_evictions` (через `Evictable`), не для Game.

```python
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
```

(Тесты — `async def` без декоратора: в проекте `asyncio_mode=auto`, как в `test_game_service_contour.py`.)

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/unit/test_retention_service.py -q`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Создать `RetentionService`**

Сначала вынести `_now()` (service.py:37-40) в новый `backend/app/game/_time.py` (3 строки + докстринг) — иначе `retention_service.py` импортировал бы `_now` из `service.py`, а `service.py` импортирует `RetentionService` → ЦИКЛ. `service.py` и `retention_service.py` оба импортируют `from ._time import _now`. Это поведенчески-нейтральный перенос функции.

Затем перенести `_evict_current`/`_evict_finished`/`enforce_limits` (service.py:94-136) в `backend/app/game/retention_service.py` как методы `RetentionService` с публичными именами `evict_current`/`evict_finished`/`enforce_limits`. Конструктор `RetentionService(repo, settings_repo)`. Логику НЕ менять (точный перенос). Зависимые импорты (`Evictable`, `Section`, `game_section`, `select_evictions` из `..domain.retention`) перенести; `_now` — из `._time`.

- [ ] **Step 4: GameService делегирует**

`backend/app/game/service.py`:
- `__init__` (44): после сохранения `self._repo`/`self._settings_repo` добавить `self._retention = RetentionService(self._repo, self._settings_repo)`. Импорт `from .retention_service import RetentionService`. Сигнатуру конструктора НЕ менять.
- **Заменить ТЕЛА** `_evict_current` (94-113), `_evict_finished` (115-130), `enforce_limits` (132-136) на тонкие делегаторы — методы оставить:
  ```python
  async def _evict_current(self, owner_id: int) -> None:
      await self._retention.evict_current(owner_id)

  async def _evict_finished(self, owner_id: int) -> None:
      await self._retention.evict_finished(owner_id)

  async def enforce_limits(self, owner_id: int) -> None:
      await self._retention.enforce_limits(owner_id)
  ```
- ВНУТРЕННИЕ вызовы НЕ трогаем: `self._evict_current(...)` (158), `self._evict_finished(...)` (173, 249, 311) теперь идут через делегаторы — изменений на этих строках нет.
- **Методы НЕ удалять.** Тесты зовут приватные напрямую: `test_game_service_contour.py:594` (`svc._evict_finished(1)`) и `:763` (`svc.enforce_limits(1)`). Оставляем делегаторы → тесты валидны, тест НЕ трогаем.

`deps.py`/`_svc` не меняются — RetentionService живёт внутри GameService.

- [ ] **Step 5: Полный suite + линт**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests`
Expected: PASS (`tests/unit/test_retention.py`, `test_game_service_contour.py`, api-ретеншн зелёные — поведение то же).

- [ ] **Step 6: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "refactor(rj): вынести вытеснение по лимитам в RetentionService (GameService делегирует)"
```

---

## Task 7 (Slice 7, мелочь, фронт): общий хук useLevels

**Что и зачем:** `HomePage.tsx` (18,21-26,58) и `GamePage.tsx` (4,32-35,41) независимо тянут `getLevels()` и резолвят id→имя. Выносим в общий хук.

**Files:**
- Create: `frontend/src/game/useLevels.ts`
- Modify: `frontend/src/pages/HomePage.tsx`, `frontend/src/pages/GamePage.tsx`
- Test: `frontend/src/game/useLevels.test.tsx` (новый)

- [ ] **Step 1: Падающий тест хука**

Создать `frontend/src/game/useLevels.test.tsx`. MSW-хендлер `/api/levels` УЖЕ есть в `src/test/msw.ts:7` (дефолт `[]`, с пометкой «тесты переопределяют по нужде») — в тесте переопределяем через `server.use(...)`, сам `msw.ts` НЕ трогаем. `renderHook`/`waitFor` — из `@testing-library/react` (^16, доступно):

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { server, http, HttpResponse } from "../test/msw";
import { useLevels } from "./useLevels";

it("resolves level id to name after load", async () => {
  server.use(http.get("/api/levels", () => HttpResponse.json([{ id: "master", name: "Мастер" }])));
  const { result } = renderHook(() => useLevels());
  await waitFor(() => expect(result.current.nameOf("master")).toBe("Мастер"));
});

it("returns undefined for unknown / nullish id", () => {
  const { result } = renderHook(() => useLevels());
  expect(result.current.nameOf(undefined)).toBeUndefined();
});
```

(`server`/`http`/`HttpResponse` экспортируются из `src/test/msw.ts`; путь импорта `../test/msw` из `src/game/`. Сверить, что глобальная тест-настройка поднимает `server` — см. `src/test/setup.ts`.)

- [ ] **Step 2: Запустить — падает**

Run: `cd frontend && npx vitest run src/game/useLevels.test.tsx`
Expected: FAIL (cannot find module ./useLevels).

- [ ] **Step 3: Реализовать хук**

Создать `frontend/src/game/useLevels.ts`:

```ts
import { useEffect, useState } from "react";
import { getLevels } from "./api";
import type { LevelDTO } from "./types";

// Справочник уровней id→имя. Отказ загрузки не критичен (имя — украшение).
export function useLevels() {
  const [levels, setLevels] = useState<LevelDTO[]>([]);
  useEffect(() => {
    let alive = true;
    getLevels()
      .then((ls) => alive && setLevels(ls))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  const byId = new Map(levels.map((l) => [l.id, l.name]));
  return {
    levels,
    nameOf: (id: string | null | undefined): string | undefined =>
      id ? byId.get(id) : undefined,
  };
}
```

- [ ] **Step 4: Тест хука зелёный**

Run: `cd frontend && npx vitest run src/game/useLevels.test.tsx`
Expected: PASS.

- [ ] **Step 5: Переключить страницы**

`HomePage.tsx`: убрать `levelNames`-state (18) и его `useEffect` (21-26); **импорт строки 3 `import { getGamesSummary, getLevels } from "../game/api";` → `import { getGamesSummary } from "../game/api";`** (getLevels больше не нужен — иначе `noUnusedLocals` валит `tsc`, tsconfig.json:7); добавить `import { useLevels } from "../game/useLevels";` и `const { nameOf } = useLevels();`; в `<GameCard>` (58) `levelName={g.level_id ? levelNames.get(g.level_id) : undefined}` → `levelName={nameOf(g.level_id)}`.
`GamePage.tsx`: убрать `levels`-state (32) и `useEffect` (33-35) и импорт `getLevels`/`LevelDTO` (4,6, если больше не нужны); добавить `useLevels`; строка 41 `const levelName = levels.find((l) => l.id === view.opponentLevelId)?.name ?? view.opponentLevelId ?? "—";` → `const levelName = nameOf(view.opponentLevelId) ?? view.opponentLevelId ?? "—";`.

- [ ] **Step 6: Фронт-тесты + тип-чек**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS (`HomePage.test.tsx`, `GamePage.test.tsx` зелёные — UI не изменился).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/game/useLevels.ts frontend/src/game/useLevels.test.tsx frontend/src/pages/HomePage.tsx frontend/src/pages/GamePage.tsx
git commit -m "refactor(rj): общий хук useLevels (вынос дубля id→имя из Home/GamePage)"
```

---

## Финальная проверка эпика

- [ ] **Step 1: Весь suite зелёный**

Run: из `backend/` — `uv run pytest -q` → PASS; из `frontend/` — `npx vitest run && npx tsc --noEmit` → PASS.

- [ ] **Step 2: Поведенческая нейтральность — глазами**

`git diff main --stat` + просмотр: изменения только структурные (перемещения/типы/делегация). Никаких новых полей в API-ответах/SSE/исходах. Содержательный диф в логике хода/исхода/протокола = нарушение scope, разобрать.

- [ ] **Step 3: Ручная проверка против живого движка (Alexey)**

Ждать Alexey: партия против движка идёт как раньше (ход человека/движка, фолы, undo, восстановление после reload). Финальный сторож нейтральности поверх тестов.

---

## Self-review

- **Покрытие находок аудита:** контроллер-граница (S1), типизация+getattr (S2), двойной service (S3), толстый роутер+app.state-фон (S4), values.py-исключения (S5), ретеншн в GameService (S6), фронт-дубль уровней (S7). Снимок/per-game-конфиг/NNUE — сознательно вне (фича-фаза, см. «Вне области»).
- **Сверка с кодом (прочитано в сессии):** сигнатуры `compute_move/forbidden_points/sync_after_undo` — `registry.py:91/132/154`; `_FakeAdapter` без `sync_after_undo` — `conftest.py:82-111`; `enforce_limits` зовётся только из теста — `test_game_service_contour.py:763`; путь `SqlSettingsRepository` — `app/game/settings_repository.py`; исключения — `values.py:42-73` (вкл. `DomainError`); DTO-поля — `dtos.py`; фронт `LevelDTO={id,name}` — `types.ts:26`.
- **Type consistency:** аксессоры (`engine_level_id/engine_level_tag/user_side/public_view`), порты (`EngineAdapter/EventHub`), `AdvanceManager.schedule/drain`, мэпперы (`summary_dto/state_payload`), `RetentionService.evict_current/evict_finished/enforce_limits`, `useLevels().nameOf` — единые по плану.
- **Известные «по образцу» (не placeholder):** фикстуры `test_retention_service.py` и MSW-handler `useLevels.test.tsx` ссылаются на существующие образцы (`test_game_service_contour.py`, `src/test/msw.ts`) намеренно — конкретные поля Game и mock-имена брать оттуда при реализации.
```
