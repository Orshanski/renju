# HTTP игровой контур (срез 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Игровой контур по HTTP: создать партию против движка, ходить, откатывать; ход движка приходит async-`202`+SSE-событием. Партии durable в SQLite, поверх фундамента среза 1 (auth/БД).

**Architecture:** Слои §4.9. Кто ходит за сторону — за фасадом `Player` (engine/соперник), сервис зовёт `players[side].take_turn()`. Единый `advance` крутит партию. **Движок крутится ТОЛЬКО в `advance`, а `advance` — ТОЛЬКО в фоне** (спека §4.6: «расчёт фоновый»): request-путь (`create`/`move`) применяет ход человека, коммитит, возвращает `202`/state сразу и планирует фоновый `advance` своей сессией (request-сессия закрыта); ход движка приходит SSE-событием. Так механика «движок vs соперник» спрятана единообразно — `202` возвращается одинаково, кто бы ни был соперником. Фолы — мемо-лог `forbidden_log` (undo = replay, движок только вперёд). `GameRepository` на SQLite (in-memory — тестовый дублёр), `EventHub` in-memory. Писатели коммитят явно (как в срезе 1).

**Tech Stack:** Python 3.13 / uv / FastAPI / SQLAlchemy async / Alembic / httpx / pytest. Движок Rapfi (живой) для integration. bd: `rj-5c9` (+ поглощает `rj-8sc`).

**Спека:** `docs/superpowers/specs/2026-06-11-http-game-contour-design.md`.

**Команды:** из `backend/`. `uv run pytest -q` · `uv run pytest <путь>::<тест> -v` · `uv run ruff check app tests scripts && uv run ruff format app tests scripts` · тип-чистота: из репо-корня `uvx pyright` (0 errors). **Pytest последовательно** (shared Rapfi). Коммит-модель: **писатели коммитят явно** (`session_scope` среза 1 только rollback+close).

---

## File Structure

- `app/domain/values.py` (**править**) — rename статусов (`rj-8sc`).
- `app/domain/undo.py` (**править**) — `check_undo` под новый статус.
- `app/models/game.py` (создать) — ORM `Game` (таблица `games`).
- `alembic/env.py` (**править**) + новая миграция — таблица `games`.
- `app/game/controllers.py` (создать) — спеки `Engine`/`User` + (де)сериализация.
- `app/game/players.py` (создать) — фасад `Player`, `EnginePlayer`/`InteractivePlayer`, фабрика.
- `app/game/repository.py` (создать) — `GameRepository` протокол + `SqlGameRepository` + `InMemoryGameRepository`.
- `app/game/event_hub.py` (создать) — `EventHub` + `InMemoryEventHub`.
- `app/game/service.py` (создать) — `GameService` (create/submit/**advance**/undo/fouls + чистые `get_game`/`load`/`list_games`). **`advance` — engine-цикл, зовётся только из фоновой задачи роутера и юнит-тестов.**
- `app/game/dtos.py` (создать) — pydantic DTO (create body, game state, level).
- `app/routers/games.py` (создать) — `/api/games*` + `/api/levels`; **`schedule_advance` — фоновый прогон `advance` своей сессией (request-путь возвращает сразу).**
- `app/app_factory.py` (**править**) — lifespan: `adapter`(E1-tolerant)/`event_hub`/`levels`/`bg_tasks`/`advancing` в `app.state`; include games-роутера; shutdown гасит фон.
- `app/config.py` (**править**) — `sse_heartbeat_s = 15`.
- `app/error_handlers.py` (**править**) — handler для `MoveRejected`/`UndoRejected` (или маппинг в роутере).
- `tests/conftest.py` (**править**) — корневая фикстура `games_api` (FakeAdapter + seed_login/wait_settled/free_move; общая для api+integration).
- `tests/unit/`, `tests/api/`, `tests/integration/` — тесты по задачам.

**Вне скоупа (не трогать):** durable `sse_events`, PvP-матчмейкинг, per-user undo-настройки, фронт. Слой среза 1 (`app/auth.py`, `app/routers/auth.py`, `app/db/*`, `app/middleware/*`) — переиспользуем, не переписываем.

---

## Task 1: Статус-машина — нейтральный rename (поглощает rj-8sc)

`AWAITING_HUMAN`/`ENGINE_THINKING` роль-связаны. Переименовать в `AWAITING_MOVE`/`OPPONENT_THINKING`; добавить `MoveRejectReason.OPPONENT_THINKING`; обновить потребителей.

**Files:** Modify `app/domain/values.py`, `app/domain/undo.py`; Test `tests/unit/test_values.py`, `tests/unit/test_undo.py`.

- [ ] **Step 1: Тест (red)** — в `tests/unit/test_values.py` добавить:
```python
def test_status_neutral_names():
    from app.domain.values import GameStatus, MoveRejectReason, UndoRejectReason
    assert GameStatus.AWAITING_MOVE.value == "awaiting_move"
    assert GameStatus.OPPONENT_THINKING.value == "opponent_thinking"
    assert MoveRejectReason.OPPONENT_THINKING.value == "opponent_thinking"
    assert UndoRejectReason.OPPONENT_THINKING.value == "opponent_thinking"
```
- [ ] **Step 2: Прогнать — FAIL.** `uv run pytest tests/unit/test_values.py::test_status_neutral_names -v`.
- [ ] **Step 3: Править `app/domain/values.py`** — в `GameStatus`: `AWAITING_HUMAN = "awaiting_human"` → `AWAITING_MOVE = "awaiting_move"`; `ENGINE_THINKING = "engine_thinking"` → `OPPONENT_THINKING = "opponent_thinking"`. В `UndoRejectReason`: `ENGINE_THINKING = "engine_thinking"` → `OPPONENT_THINKING = "opponent_thinking"`. В `MoveRejectReason` добавить `OPPONENT_THINKING = "opponent_thinking"`.
- [ ] **Step 4: Править `app/domain/undo.py`** — в `check_undo` заменить `if status is GameStatus.ENGINE_THINKING: raise UndoRejected(UndoRejectReason.ENGINE_THINKING)` на `if status is GameStatus.OPPONENT_THINKING: raise UndoRejected(UndoRejectReason.OPPONENT_THINKING)`.
- [ ] **Step 5: Поправить существующих потребителей старых статусов.** Полный список — `grep -rn -E "AWAITING_HUMAN|ENGINE_THINKING|awaiting_human|engine_thinking" app tests`:
  - `tests/unit/test_values.py::test_game_status_values_match_spec_enum` — **и символы, и строковые литералы**: `GameStatus.AWAITING_HUMAN.value == "awaiting_human"` → `GameStatus.AWAITING_MOVE.value == "awaiting_move"`; `GameStatus.ENGINE_THINKING.value == "engine_thinking"` → `GameStatus.OPPONENT_THINKING.value == "opponent_thinking"`; `not GameStatus.AWAITING_HUMAN.is_finished` → `not GameStatus.AWAITING_MOVE.is_finished`.
  - `tests/unit/test_undo.py` — символы `GameStatus.AWAITING_HUMAN`→`AWAITING_MOVE` (строки 12, 17, 41, 46), `GameStatus.ENGINE_THINKING`→`OPPONENT_THINKING` (23), `UndoRejectReason.ENGINE_THINKING`→`OPPONENT_THINKING` (24); имена тестов `test_default_policy_allows_undo_in_awaiting_human`→`…_awaiting_move` (11), `test_engine_thinking_rejects`→`test_opponent_thinking_rejects` (21).
  - `tests/unit/test_game.py:71` — закомментированная строка `# def test_engine_thinking_rejected(): ...` (косметика, на прогон не влияет; обновить ради гигиены).

> **B3 (ревью 2026-06-12):** голый `grep -l ENGINE_THINKING` ловит только СИМВОЛ — строковые литералы `"engine_thinking"`/`"awaiting_human"` (test_values.py:30-31) и имена тестов он пропускает, и Step 6 останется красным. Менять и символы, и литералы.
- [ ] **Step 6: Прогнать — green.** `uv run pytest -q` (всё зелёное); `uv run ruff check app tests`; из репо-корня `uvx pyright` (0 errors).
- [ ] **Step 7: Коммит** — `git commit -m "refactor(rj-8sc): нейтральные статусы AWAITING_MOVE/OPPONENT_THINKING (+ MoveRejectReason)"`.

---

## Task 2: ORM-модель `Game` + миграция `games`

**Files:** Create `app/models/game.py`; Modify `alembic/env.py`; Create `alembic/versions/*_games.py`; Test `tests/unit/test_migration.py` (дополнить).

- [ ] **Step 1: `app/models/game.py`**
```python
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


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
```
- [ ] **Step 2: Править `alembic/env.py`** — рядом с `import app.models.user  # noqa: F401` добавить строкой ниже: `import app.models.game  # noqa: F401`.
- [ ] **Step 2b: Править `tests/conftest.py`** — в фикстурах `engine` И `app` рядом с `import app.models.user  # noqa: F401` добавить `import app.models.game  # noqa: F401`. Иначе `Base.metadata.create_all` не создаст таблицу `games` для тестов, поднимающих БД без приложения (фикстура `session`/`engine` — напр. `test_sql_crud` в Task 4): модель регистрируется в `Base.metadata` только при импорте её модуля.
- [ ] **Step 3: Сгенерировать миграцию** — `uv run alembic revision --autogenerate -m "games"`. Проверить в `alembic/versions/*_games.py`: `op.create_table("games", ...)` со всеми колонками; `owner_id` с `sa.ForeignKeyConstraint(["owner_id"], ["users.id"])` ВНУТРИ `create_table`; `forbidden_log` server_default? (autogenerate может опустить — для JSON это ок, ORM-default `dict` покрывает на вставке). PK `id` тип String.
- [ ] **Step 4: Тест миграции** — в `tests/unit/test_migration.py` добавить:
```python
def test_alembic_upgrade_creates_games(tmp_path, monkeypatch):
    import subprocess
    from sqlalchemy import create_engine, inspect
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    insp = inspect(eng)
    assert "games" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("games")}
    assert {"id", "owner_id", "controllers", "moves", "status", "undo_count",
            "forbidden_log", "created_at", "updated_at"} <= cols
    fks = insp.get_foreign_keys("games")
    assert any(fk["referred_table"] == "users" for fk in fks)
    eng.dispose()
```
- [ ] **Step 5: Прогнать — PASS.** `uv run pytest tests/unit/test_migration.py -v`.
- [ ] **Step 6: Линт/тип/коммит.** `uv run ruff check app tests` · `uvx pyright` (из корня) · `git commit -m "feat(rj-5c9): ORM-модель Game + миграция games (FK→users)"`.

---

## Task 3: Контролёры + фасад `Player` + фабрика

`controllers` хранят данные (`Engine(level_id)`/`User(user_id)`); фасад `Player` прячет «движок/соперник».

**Files:** Create `app/game/__init__.py`, `app/game/controllers.py`, `app/game/players.py`; Test `tests/unit/test_players.py`.

- [ ] **Step 1: Тесты (red)** `tests/unit/test_players.py`
```python
import pytest
from app.game.controllers import Engine, User, controller_from_json, controller_to_json
from app.game.players import EnginePlayer, InteractivePlayer, make_player

def test_controller_roundtrip():
    assert controller_from_json(controller_to_json(Engine("master"))) == Engine("master")
    assert controller_from_json(controller_to_json(User(7))) == User(7)

async def test_interactive_player_take_turn_none():
    p = InteractivePlayer(7)
    assert await p.take_turn([(7, 7)]) is None

async def test_make_player_dispatch():
    fake_adapter = object()
    levels = {"master": object()}  # level_id → params
    assert isinstance(make_player(User(7), fake_adapter, levels), InteractivePlayer)
    assert isinstance(make_player(Engine("master"), fake_adapter, levels), EnginePlayer)
```
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: `app/game/controllers.py`**
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Engine:
    level_id: str


@dataclass(frozen=True)
class User:
    user_id: int


Controller = Engine | User


def controller_to_json(c: Controller) -> dict:
    if isinstance(c, Engine):
        return {"kind": "engine", "level_id": c.level_id}
    return {"kind": "user", "user_id": c.user_id}


def controller_from_json(d: dict) -> Controller:
    return Engine(d["level_id"]) if d["kind"] == "engine" else User(d["user_id"])
```
- [ ] **Step 4: `app/game/players.py`**
```python
from collections.abc import Sequence
from typing import Protocol

from app.domain.values import Point
from app.game.controllers import Controller, Engine, User
from app.game_service import engine_move


class Player(Protocol):
    async def take_turn(self, moves: Sequence[Point]) -> Point | None: ...


class InteractivePlayer:
    def __init__(self, user_id: int):
        self.user_id = user_id

    async def take_turn(self, moves: Sequence[Point]) -> Point | None:
        return None  # ход придёт подачей


class EnginePlayer:
    def __init__(self, adapter, params):
        self._adapter = adapter
        self._params = params

    async def take_turn(self, moves: Sequence[Point]) -> Point | None:
        return await engine_move(self._adapter, moves, self._params)


def make_player(ctl: Controller, adapter, levels: dict) -> Player:
    if isinstance(ctl, User):
        return InteractivePlayer(ctl.user_id)
    return EnginePlayer(adapter, levels[ctl.level_id])  # levels: level_id → EngineParams
```
- [ ] **Step 5: Прогнать — PASS.** `uv run pytest tests/unit/test_players.py -v`.
- [ ] **Step 6: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): контролёры (Engine/User) + фасад Player + фабрика"`.

---

## Task 4: `GameRepository` (SQLite + in-memory)

**Files:** Create `app/game/repository.py`; Test `tests/unit/test_game_repository.py`.

- [ ] **Step 1: Тесты (red)** `tests/unit/test_game_repository.py` (репо хранит/отдаёт `Game`-ORM; для SQLite — фикстура `session`/`engine` из conftest)
```python
import pytest
from app.game.repository import InMemoryGameRepository, SqlGameRepository
from app.models.game import Game

def _game(gid="g1", owner=1):
    return Game(id=gid, owner_id=owner, controllers={"black": {"kind": "user", "user_id": owner},
               "white": {"kind": "engine", "level_id": "master"}}, moves=[[7, 7]],
               status="awaiting_move", undo_count=0, forbidden_log={})

async def test_inmemory_crud():
    repo = InMemoryGameRepository()
    await repo.create(_game())
    assert (await repo.get("g1")).id == "g1"
    assert await repo.get("missing") is None
    assert [g.id for g in await repo.list_by_owner(1)] == ["g1"]

async def test_sql_crud(session):
    # users-строка нужна под FK; берём реальный id (не полагаемся на autoincrement=1)
    from app.dal import users as udal
    uid = await udal.create_user(session, "alice", "pw"); await session.commit()
    repo = SqlGameRepository(session)
    await repo.create(_game(owner=uid))
    got = await repo.get("g1")
    assert got.id == "g1" and got.moves == [[7, 7]]
    got.status = "finished_draw"
    await repo.update(got)
    assert (await repo.get("g1")).status == "finished_draw"
```
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: `app/game/repository.py`**
```python
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Game


class GameRepository(Protocol):
    async def create(self, game: Game) -> None: ...
    async def get(self, game_id: str) -> Game | None: ...
    async def list_by_owner(self, owner_id: int) -> list[Game]: ...
    async def update(self, game: Game) -> None: ...


class SqlGameRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def create(self, game: Game) -> None:
        self._s.add(game)
        await self._s.commit()  # писатель коммитит явно (срез 1)

    async def get(self, game_id: str) -> Game | None:
        return await self._s.get(Game, game_id)

    async def list_by_owner(self, owner_id: int) -> list[Game]:
        return list((await self._s.execute(
            select(Game).where(Game.owner_id == owner_id).order_by(Game.created_at))).scalars())

    async def update(self, game: Game) -> None:
        await self._s.commit()  # game уже tracked сессией; коммитим изменения


class InMemoryGameRepository:
    def __init__(self):
        self._d: dict[str, Game] = {}

    async def create(self, game: Game) -> None:
        self._d[game.id] = game

    async def get(self, game_id: str) -> Game | None:
        return self._d.get(game_id)

    async def list_by_owner(self, owner_id: int) -> list[Game]:
        return [g for g in self._d.values() if g.owner_id == owner_id]

    async def update(self, game: Game) -> None:
        self._d[game.id] = game
```
> Примечание: `SqlGameRepository.update` полагается на то, что `game` — tracked ORM-объект из той же сессии (его поля изменены сервисом); `commit()` персистит. JSON-колонки (`moves`/`forbidden_log`) при мутации списка/словаря на месте требуют переприсваивания (`game.moves = [...]`), иначе SQLAlchemy не заметит изменения — сервис всегда присваивает новый список/словарь (см. Task 7/8).
> Порядок `list_by_owner` РАСХОДИТСЯ у реализаций: Sql — `ORDER BY created_at`, in-memory дублёр — порядок вставки (`created_at` у in-memory `Game` без БД не проставлен). Сейчас ни один тест не проверяет межигровой порядок (только одноэлементный `test_inmemory_crud`), так что безвредно. Если появится тест на порядок против дублёра — он разойдётся с продом; тогда либо сортировать дублёр явно, либо тестировать порядок только против Sql.
- [ ] **Step 4: Прогнать — PASS.**
- [ ] **Step 5: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): GameRepository (SQLite + in-memory дублёр)"`.

---

## Task 5: `EventHub` (in-memory pub/sub + курсор)

**Files:** Create `app/game/event_hub.py`; Test `tests/unit/test_event_hub.py`.

- [ ] **Step 1: Тесты (red)** `tests/unit/test_event_hub.py`
```python
import asyncio
import pytest
from app.game.event_hub import InMemoryEventHub

async def test_publish_assigns_monotonic_seq():
    hub = InMemoryEventHub()
    s1 = hub.publish("g1", "move", {"by": "black"})
    s2 = hub.publish("g1", "status", {"status": "awaiting_move"})
    assert s2 == s1 + 1

async def test_replay_since_cursor():
    hub = InMemoryEventHub()
    hub.publish("g1", "move", {"n": 1})
    hub.publish("g1", "move", {"n": 2})
    got = []
    async def consume():
        async for ev in hub.subscribe("g1", since=1):
            got.append(ev); 
            if ev["payload"].get("n") == 3: break
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    hub.publish("g1", "move", {"n": 3})  # live
    await asyncio.wait_for(task, 1)
    # реплей с курсора 1 даёт seq>1 (n=2) + live (n=3)
    assert [e["payload"]["n"] for e in got] == [2, 3]

async def test_reset_when_cursor_in_future():
    hub = InMemoryEventHub()
    hub.publish("g1", "move", {"n": 1})
    first = None
    async for ev in hub.subscribe("g1", since=999):
        first = ev; break
    assert first["type"] == "reset"

async def test_subscribe_heartbeat_ping_on_idle():
    hub = InMemoryEventHub()
    gen = hub.subscribe("g1", since=0, idle_timeout=0.02)
    ev = await asyncio.wait_for(gen.__anext__(), 1)  # нет событий → ping, подписка ЖИВА
    assert ev["type"] == "ping"
    nxt = await asyncio.wait_for(gen.__anext__(), 1)  # второй idle → снова ping (не StopAsyncIteration)
    assert nxt["type"] == "ping"
    await gen.aclose()
```
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: `app/game/event_hub.py`**
```python
import asyncio
from collections.abc import AsyncIterator


class InMemoryEventHub:
    def __init__(self):
        self._seq: dict[str, int] = {}
        self._log: dict[str, list[dict]] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def publish(self, game_id: str, type_: str, payload: dict) -> int:
        seq = self._seq.get(game_id, 0) + 1
        self._seq[game_id] = seq
        ev = {"seq": seq, "type": type_, "payload": payload}
        self._log.setdefault(game_id, []).append(ev)
        for q in self._subs.get(game_id, []):
            q.put_nowait(ev)
        return seq

    def cursor(self, game_id: str) -> int:
        return self._seq.get(game_id, 0)

    async def subscribe(
        self, game_id: str, since: int, idle_timeout: float | None = None
    ) -> AsyncIterator[dict]:
        cur = self._seq.get(game_id, 0)
        if since > cur:  # курсор «из будущего» — недостижим
            yield {"seq": cur, "type": "reset", "payload": {}}
            return
        for ev in self._log.get(game_id, []):  # реплей из буфера
            if ev["seq"] > since:
                yield ev
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(game_id, []).append(q)
        try:
            while True:
                if idle_timeout is None:
                    yield await q.get()
                else:
                    try:  # таймаут оборачивает q.get() ВНУТРИ генератора (см. note)
                        yield await asyncio.wait_for(q.get(), idle_timeout)
                    except TimeoutError:  # idle → ping, подписку НЕ закрываем
                        yield {"seq": self._seq.get(game_id, 0), "type": "ping", "payload": {}}
        finally:
            self._subs[game_id].remove(q)
```
> `subscribe` отдаёт реплей-из-буфера (seq>since), затем live из очереди. `idle_timeout` (если задан) оборачивает **`q.get()` ВНУТРИ генератора** и на таймауте отдаёт `ping`, НЕ закрывая подписку. **Критично (B-2, ревью 2026-06-12):** оборачивать `agen.__anext__()` СНАРУЖИ в `wait_for` нельзя — отмена прокрутит `finally` генератора (снимет очередь), генератор закроется, и idle-стрим умрёт на первом heartbeat вместо ping. Отмена `q.get()` потерю события не вызывает: `put_nowait` уже положил item в deque, отменяется лишь futures-ожидание getter'а.
- [ ] **Step 4: Прогнать — PASS.** (тесты последовательно).
- [ ] **Step 5: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): EventHub (in-memory pub/sub, курсор, reset)"`.

---

## Task 6: `GameService` — создание + fouls-мемо

**Files:** Create `app/game/service.py` (часть 1: `__init__`, `fouls`); Test `tests/unit/test_game_service_contour.py`.

- [ ] **Step 1: Тесты (red)** `tests/unit/test_game_service_contour.py` (фейковый адаптер: `forbidden_points`→фикс, `compute_move`→фикс)
```python
import pytest
from app.game.event_hub import InMemoryEventHub
from app.game.repository import InMemoryGameRepository
from app.game.service import GameService

class FakeAdapter:
    def __init__(self): self.forbid = [(3, 3)]; self.move = (8, 8)
    async def forbidden_points(self, moves): return list(self.forbid)
    async def compute_move(self, moves, params, allowed_zone=None): return self.move

def _svc(adapter=None):
    return GameService(repo=InMemoryGameRepository(), hub=InMemoryEventHub(),
                       adapter=adapter or FakeAdapter(), levels={"master": object()})

async def test_fouls_memoized_one_engine_call():
    svc = _svc()
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points
    async def counting(moves):
        svc._adapter.calls += 1; return await orig(moves)
    svc._adapter.forbidden_points = counting
    from app.models.game import Game
    g = Game(id="g", owner_id=1, controllers={}, moves=[[7,7],[8,8]], status="awaiting_move",
             undo_count=0, forbidden_log={})
    f1 = await svc.fouls(g, g.moves)   # len 2 (чёрные) → движок, запись
    f2 = await svc.fouls(g, g.moves)   # из лога
    assert f1 == [(3, 3)] and f2 == [(3, 3)] and svc._adapter.calls == 1
    assert g.forbidden_log["2"] == [[3, 3]]

async def test_fouls_white_to_move_empty_no_engine():
    svc = _svc(); svc._adapter.calls = 0
    from app.models.game import Game
    g = Game(id="g", owner_id=1, controllers={}, moves=[[7,7]], status="awaiting_move",
             undo_count=0, forbidden_log={})
    assert await svc.fouls(g, g.moves) == []  # len 1 (белые) → []
```
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: `app/game/service.py` (часть 1)**
```python
import uuid
from collections.abc import Sequence

from app.domain.opening import CENTER
from app.domain.values import Color, Point, color_to_move
from app.game.controllers import Controller, controller_to_json
from app.models.game import Game


class GameService:
    def __init__(self, repo, hub, adapter, levels: dict):
        self._repo = repo
        self._hub = hub
        self._adapter = adapter
        self._levels = levels  # level_id → EngineParams

    async def fouls(self, game: Game, moves: Sequence[Point]) -> list[Point]:
        """Мемо-фолы: forbidden_log[str(len)] есть → вернуть; иначе движок + запись.
        Непусто только на ход чёрных."""
        key = str(len(moves))
        log = game.forbidden_log
        if key in log:
            return [tuple(p) for p in log[key]]
        if color_to_move(len(moves)) is Color.BLACK:
            pts = await self._adapter.forbidden_points(moves)
        else:
            pts = []
        game.forbidden_log = {**log, key: [list(p) for p in pts]}  # переприсвоить (JSON-mutation)
        return list(pts)
```
- [ ] **Step 4: Прогнать — PASS.**
- [ ] **Step 5: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): GameService + fouls-мемо (forbidden_log, движок ровно раз на позицию)"`.

---

## Task 7: `advance` — единый цикл продвижения

**Files:** Modify `app/game/service.py` (добавить `_players`, `_is_engine`, `_next_status`, `create_game`, `advance`); Test `tests/unit/test_game_service_contour.py` (нейтральность).

- [ ] **Step 1: Тесты (red)** — добавить (движок крутится ТОЛЬКО в `advance`; `create_game` его НЕ зовёт — в проде это делает фоновая задача роутера, в юните дёргаем `advance` вручную):
```python
async def test_create_hve_human_black_pending_engine():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    # центр (ход 1 = чёрные) предзаполнен = ход человека; ход 2 за движком-белым → ждём фон
    assert g.moves == [[7, 7]] and g.status == "opponent_thinking"

async def test_create_hve_human_white_awaits_human():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="white")
    # центр = ход 1 = чёрные = движок (предзаполнен); ход 2 за человеком-белым
    assert g.moves == [[7, 7]] and g.status == "awaiting_move"

async def test_advance_drives_engine_move():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    await svc.advance(g)  # «фон»: движок-белый ходит 2-м
    assert g.moves == [[7, 7], [8, 8]] and g.status == "awaiting_move"

async def test_neutrality_both_interactive_pvp_no_autoplay():
    svc = _svc()
    from app.models.game import Game
    g = Game(id="g", owner_id=1, moves=[[7, 7]], undo_count=0, forbidden_log={},
             controllers={"black": {"kind": "user", "user_id": 1},
                          "white": {"kind": "user", "user_id": 2}}, status="awaiting_move")
    await svc._repo.create(g)
    await svc.advance(g)
    assert g.moves == [[7, 7]] and g.status == "awaiting_move"  # advance НЕ ходит сам

async def test_advance_engine_error_publishes_error_event():
    from app.rapfi.adapter import EngineError
    svc = _svc()
    async def boom(moves, params, allowed_zone=None):
        raise EngineError("twice")
    svc._adapter.compute_move = boom
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    assert g.status == "opponent_thinking"
    await svc.advance(g)  # движок падает → error-событие, статус НЕ меняется (§4.8 доиграет позже)
    assert g.status == "opponent_thinking"
    assert any(e["type"] == "error" for e in svc._hub._log.get(g.id, []))
```
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: Добавить в `app/game/service.py`**
```python
from app.domain.values import GameStatus, color_of_move
from app.game.controllers import Engine, User, controller_from_json
from app.game.players import make_player
from app.game_service import apply_move
from app.domain.rules import outcome_after
from app.rapfi.adapter import EngineError


# --- в class GameService ---

    def _players(self, game: Game) -> dict[Color, object]:
        return {Color(side): make_player(controller_from_json(c), self._adapter, self._levels)
                for side, c in game.controllers.items()}

    def _is_engine(self, game: Game, side: Color) -> bool:
        return isinstance(controller_from_json(game.controllers[side.value]), Engine)

    def _next_status(self, game: Game, moves: Sequence[Point]) -> str:
        """Статус ПОСЛЕ применённого хода, позиционно (без роли): завершено → finished_*;
        следующий ход за движком → opponent_thinking (request-путь вернётся сразу, движок
        сходит фоновым advance); за интерактивной стороной → awaiting_move."""
        outcome = outcome_after(moves)
        if outcome is not None:
            return outcome.value
        side = color_to_move(len(moves))
        return (GameStatus.OPPONENT_THINKING.value if self._is_engine(game, side)
                else GameStatus.AWAITING_MOVE.value)

    async def create_game(self, owner_id: int, opponent_level: str, human_color: str) -> Game:
        human = Color(human_color)
        engine_side = Color.WHITE if human is Color.BLACK else Color.BLACK
        controllers = {human.value: controller_to_json(User(owner_id)),
                       engine_side.value: controller_to_json(Engine(opponent_level))}
        game = Game(id=str(uuid.uuid4()), owner_id=owner_id, controllers=controllers,
                    moves=[list(CENTER)], status=GameStatus.AWAITING_MOVE.value,
                    undo_count=0, forbidden_log={})
        game.status = self._next_status(game, [CENTER])  # opponent_thinking, если ход 2 за движком
        await self._repo.create(game)
        return game  # advance НЕ здесь — фоновый прогон планирует роутер (Task 10)

    async def advance(self, game: Game) -> None:
        """Единый цикл продвижения. Зовётся ТОЛЬКО из фоновой задачи роутера (своя сессия)
        или из юнит-теста. take_turn() engine-стороны (расчёт движка) крутится только здесь."""
        players = self._players(game)
        while True:
            moves = [tuple(m) for m in game.moves]
            outcome = outcome_after(moves)
            if outcome is not None:
                game.status = outcome.value
                self._hub.publish(game.id, "status", {"status": game.status})
                await self._repo.update(game); return
            side = color_to_move(len(moves))
            if not self._is_engine(game, side):  # интерактивная — ждём подачу
                game.status = GameStatus.AWAITING_MOVE.value
                fb = await self.fouls(game, moves)
                if fb:
                    self._hub.publish(game.id, "forbidden", {"points": [list(p) for p in fb]})
                self._hub.publish(game.id, "status", {"status": game.status})
                await self._repo.update(game); return
            game.status = GameStatus.OPPONENT_THINKING.value
            self._hub.publish(game.id, "status", {"status": game.status})
            await self._repo.update(game)
            try:
                mv = await players[side].take_turn(moves)
            except EngineError as e:  # сбой движка после ретрая → событие error, статус не трогаем
                self._hub.publish(game.id, "error", {"message": str(e)})
                return  # остаётся opponent_thinking; §4.8-восстановление доиграет при доступе
            assert mv is not None  # engine-сторона всегда даёт ход (None только у Interactive)
            fb = await self.fouls(game, moves) if side is Color.BLACK else []  # фолы только на ход чёрных
            game.moves = [list(p) for p in apply_move(moves, mv, forbidden=fb)]
            self._hub.publish(game.id, "move",
                              {"by": color_of_move(len(game.moves) - 1).value,
                               "point": list(mv), "move_index": len(game.moves) - 1})
            await self._repo.update(game)
```
> `create_game` ставит статус позиционно (`_next_status`) и НЕ ходит движком; фоновый `advance` планирует роутер (Task 10), request-путь возвращает state сразу (спека §4.6; cursor снимается до advance — гонки create→подписка нет). `advance` крутит через фасад `players[side].take_turn`; `is_engine` — только в оркестрации (статус/выбор), в ход не течёт. JSON-колонки переприсваиваются (`game.moves = [...]`, `game.forbidden_log = {...}` внутри `fouls`).
> **Асимметрия мемо (норма, не баг — M-2, ревью 2026-06-12):** в engine-ветке фолы берутся `await self.fouls(...) if side is Color.BLACK else []` — на ход БЕЛОЙ engine-стороны `fouls` НЕ зовётся, поэтому ключа `forbidden_log[str(len)]` для белых позиций может не быть. Безопасно: фолы бывают только у чёрных (для белых всегда `[]`), а потребители читают `forbidden_log.get(key, [])` или досчитывают `fouls` лениво (тот сам впишет ключ). `forbidden_log` НЕ обязан быть плотным.
- [ ] **Step 4: Прогнать — PASS** (create→`opponent_thinking` для HvE-человек-чёрный; `advance` доигрывает; PvP-форма не ходит сама). `uv run pytest tests/unit/test_game_service_contour.py -v`.
- [ ] **Step 5: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): advance — единый цикл через фасад Player (нейтральность HvE/PvP/EvE)"`.

---

## Task 8: Подача хода + undo (replay лога)

**Files:** Modify `app/game/service.py` (`submit_move`, `undo`); Test `tests/unit/test_game_service_contour.py`.

- [ ] **Step 1: Тесты (red)** — добавить (submit применяет ход человека и НЕ ходит движком; ответ движка — отдельным `advance`, как фон в проде):
```python
async def test_submit_move_then_engine_replies_via_advance():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="white")
    svc._adapter.move = (5, 5)
    g = await svc.submit_move(g.id, user_id=1, point=(6, 6))  # ход 2 белые (человек)
    assert g.moves == [[7, 7], [6, 6]] and g.status == "opponent_thinking"  # ждём движок
    await svc.advance(g)  # «фон»: движок-чёрный ходит 3-м
    assert g.moves == [[7, 7], [6, 6], [5, 5]] and g.status == "awaiting_move"

async def test_submit_not_your_turn_pvp_form():
    from app.domain.values import MoveRejected, MoveRejectReason
    from app.models.game import Game
    svc = _svc()
    g = Game(id="g", owner_id=1, moves=[[7, 7]], undo_count=0, forbidden_log={},
             controllers={"black": {"kind": "user", "user_id": 1},
                          "white": {"kind": "user", "user_id": 2}}, status="awaiting_move")
    await svc._repo.create(g)
    # ход 2 = белые = user 2; чёрный (user 1, участник) подаёт не в свою очередь
    with pytest.raises(MoveRejected) as e:
        await svc.submit_move("g", user_id=1, point=(6, 6))
    assert e.value.reason is MoveRejectReason.NOT_YOUR_TURN

async def test_submit_foreign_user_not_found():
    from app.exceptions import NotFoundError
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    with pytest.raises(NotFoundError):  # user 2 не участник одиночной HvE-партии
        await svc.submit_move(g.id, user_id=2, point=(6, 6))

async def test_undo_pure_replay_no_engine():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="white")
    svc._adapter.move = (6, 6)
    g = await svc.submit_move(g.id, user_id=1, point=(8, 8))  # ход 2 белые (реальный ход человека)
    await svc.advance(g)  # «фон»: движок-чёрный ходит 3-м → [[7,7],[8,8],[6,6]]
    assert g.moves == [[7, 7], [8, 8], [6, 6]]
    # форбиды позиций уже в forbidden_log → undo без движка
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points
    async def counting(m):
        svc._adapter.calls += 1
        return await orig(m)
    svc._adapter.forbidden_points = counting
    g = await svc.undo(g.id, user_id=1)
    # откат белых: снимаем ход 3 (движок) и ход 2 (человек) → назад к [[7,7]]
    assert g.moves == [[7, 7]] and "2" not in g.forbidden_log and "3" not in g.forbidden_log
    assert svc._adapter.calls == 0  # undo без движка
```
> **B1 (ревью 2026-06-12):** undo тестируем по человеку-БЕЛОМУ после реального хода — у человека-чёрного единственный «ход» это предзаполненный центр (preset-floor), `undo_truncate` бросил бы `NOTHING_TO_UNDO`. **B2:** `NOT_YOUR_TURN` достижим лишь в PvP-форме (оба контролёра `User`); в одиночном HvE чужой `user_id` отсекается раньше как `NotFoundError` (`_load_owned`) — это покрывают два отдельных теста.
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: Добавить в `app/game/service.py`**
```python
from app.domain.values import (MoveRejected, MoveRejectReason, UndoRejected,
                               color_to_move)
from app.domain.undo import UndoPolicy, check_undo
from app.domain.game import undo_truncate
from app.exceptions import NotFoundError


    async def _load_owned(self, game_id: str, user_id: int) -> Game:
        game = await self._repo.get(game_id)
        if game is None or user_id not in self._controller_user_ids(game):
            raise NotFoundError("Game not found")
        return game

    def _controller_user_ids(self, game: Game) -> set[int]:
        out = set()
        for c in game.controllers.values():
            ctl = controller_from_json(c)
            if isinstance(ctl, User):
                out.add(ctl.user_id)
        return out

    async def submit_move(self, game_id: str, user_id: int, point: Point) -> Game:
        game = await self._load_owned(game_id, user_id)
        if game.status != GameStatus.AWAITING_MOVE.value:
            raise MoveRejected(MoveRejectReason.OPPONENT_THINKING)
        moves = [tuple(m) for m in game.moves]
        side = color_to_move(len(moves))
        ctl = controller_from_json(game.controllers[side.value])
        if not (isinstance(ctl, User) and ctl.user_id == user_id):
            raise MoveRejected(MoveRejectReason.NOT_YOUR_TURN)
        fb = await self.fouls(game, moves)  # из лога (записан advance'ом), без движка
        game.moves = [list(p) for p in apply_move(moves, point, forbidden=fb)]
        self._hub.publish(game.id, "move",
                          {"by": color_of_move(len(game.moves) - 1).value,
                           "point": list(point), "move_index": len(game.moves) - 1})
        game.status = self._next_status(game, [tuple(m) for m in game.moves])
        if GameStatus(game.status).is_finished:  # ход человека завершил партию — фона не будет
            self._hub.publish(game.id, "status", {"status": game.status})
        await self._repo.update(game)
        return game  # advance НЕ здесь: при opponent_thinking роутер запланирует фоновый прогон

    async def undo(self, game_id: str, user_id: int) -> Game:
        game = await self._load_owned(game_id, user_id)
        check_undo(policy=UndoPolicy(), status=GameStatus(game.status), undo_count=game.undo_count)
        my_side = next(s for s, c in game.controllers.items()
                       if controller_from_json(c) == User(user_id))
        new_moves = undo_truncate(moves=[tuple(m) for m in game.moves], for_color=Color(my_side))
        k = len(new_moves)
        game.moves = [list(p) for p in new_moves]
        game.forbidden_log = {key: v for key, v in game.forbidden_log.items() if int(key) <= k}
        game.undo_count += 1
        game.status = GameStatus.AWAITING_MOVE.value
        self._hub.publish(game.id, "undo", {"move_count": k})
        fb = await self.fouls(game, new_moves)  # из лога (replay), без движка
        if fb:
            self._hub.publish(game.id, "forbidden", {"points": [list(p) for p in fb]})
        await self._repo.update(game)
        return game
```
> `submit_move`: очередь по контролёру (`NOT_YOUR_TURN`/`OPPONENT_THINKING`), `apply_move` (фолы из лога), статус через `_next_status` — и ВОЗВРАТ (без движка). `opponent_thinking` публикует фоновый `advance` (он сам ставит+публикует статус на входе в engine-ветку); завершение ходом человека публикуется здесь (фона не будет). `undo`: усекает `moves` и ключи `forbidden_log > k`, фолы текущей позиции уже в логе → `fouls` без движка.
- [ ] **Step 4: Прогнать — PASS.** `uv run pytest tests/unit/test_game_service_contour.py -v`.
- [ ] **Step 5: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): submit_move (очередь по контролёру) + undo (replay forbidden_log, без движка)"`.

---

## Task 9: §4.8-восстановление — идемпотентный `advance` + чистые `get_game`/`load`

Восстановление застрявшего `opponent_thinking` — **тот же фоновый `advance`** (роутер планирует его при доступе, Task 10/12), а не отдельный код-путь в сервисе. Здесь — два чистых геттера сервиса + доказательство идемпотентности `advance` (повторный прогон не задваивает ход движка: мемо `fouls` + детерминизм Rapfi, §4.8). Геттеры держим сервис свободным от фоновых сессий (их владеет роутер).

**Files:** Modify `app/game/service.py` (`get_game`, `load`, `list_games`); Test `tests/unit/test_game_service_contour.py`.

- [ ] **Step 1: Тесты (red)** — добавить:
```python
async def test_advance_recovers_and_is_idempotent():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    # create оставил opponent_thinking (ход 2 за движком); фоновой задачи в юните нет
    assert g.status == "opponent_thinking" and g.moves == [[7, 7]]
    await svc.advance(g)  # «восстановление»: движок-белый ходит 2-м
    assert g.moves == [[7, 7], [8, 8]] and g.status == "awaiting_move"
    snapshot = [list(m) for m in g.moves]
    await svc.advance(g)  # повтор — no-op: ход человека-чёрного, advance ждёт подачу
    assert g.moves == snapshot and g.status == "awaiting_move"

async def test_advance_recovery_when_engine_move_already_applied():
    # реальный краш: ход движка УЖЕ закоммичен, но статус застрял opponent_thinking
    # (упали между repo.update(move) и переходом в awaiting_move) → recovery НЕ двигает повторно
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    await svc.advance(g)  # движок сходил → [[7,7],[8,8]], awaiting_move (ход человека-чёрного)
    g.status = "opponent_thinking"; await svc._repo.update(g)  # симулируем застрявший статус
    svc._adapter.calls = 0
    orig = svc._adapter.compute_move
    async def counting(*a, **k):
        svc._adapter.calls += 1
        return await orig(*a, **k)
    svc._adapter.compute_move = counting
    await svc.advance(g)  # позиция = ход человека → advance оседает на awaiting_move без движка
    assert g.moves == [[7, 7], [8, 8]] and g.status == "awaiting_move"
    assert svc._adapter.calls == 0  # движок НЕ дёрнут — ход не задвоен

async def test_get_game_pure_access_check():
    from app.exceptions import NotFoundError
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    assert (await svc.get_game(g.id, user_id=1)).id == g.id  # участник — ок
    with pytest.raises(NotFoundError):
        await svc.get_game(g.id, user_id=2)  # чужой → 404
    with pytest.raises(NotFoundError):
        await svc.get_game("missing", user_id=1)
    assert g.status == "opponent_thinking"  # get_game НЕ ходит движком (фон — забота роутера)
```
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: Добавить в `app/game/service.py`**
```python
    async def get_game(self, game_id: str, user_id: int) -> Game:
        # чистый доступ с проверкой участия; восстановление (фоновый advance при
        # opponent_thinking) планирует роутер — сервис не владеет фоновыми сессиями.
        return await self._load_owned(game_id, user_id)

    async def load(self, game_id: str) -> Game | None:
        # сырая загрузка по id (без проверки участия) — для фоновой задачи роутера,
        # которая прогоняет advance уже после того, как запрос проверил доступ.
        return await self._repo.get(game_id)

    async def list_games(self, owner_id: int) -> list[Game]:
        return await self._repo.list_by_owner(owner_id)
```
> §4.8 (решение A): durable-партия → застрявший `opponent_thinking` (фоновая `advance`-задача умерла с рестартом; `advancing` пуст после рестарта) доигрывается тем же фоновым `advance`, который роутер планирует при `GET`/SSE-доступе (Task 10/12).
> **Почему фон не затирает ход человека (ключевой инвариант, не «last-write-wins»):** подача хода во время `opponent_thinking` отвергается `MoveRejected(OPPONENT_THINKING)`→409 (`submit_move`, Task 8) — человек НЕ может закоммитить ход, пока партия в `opponent_thinking`, а именно в этом статусе крутится `advance`. Фоновый `advance` и подача человека взаимоисключены статусом-воротами, поэтому recovery-`advance` не перезапишет только что закоммиченный ход (нет lost-update).
> **Идемпотентность повторного прогона** (покрыта юнитами `test_advance_recovers_and_is_idempotent` + `test_advance_recovery_when_engine_move_already_applied`): повтор после оседания на `awaiting_move` ничего не двигает (ждёт подачу), и если ход движка УЖЕ на доске (краш после `repo.update` хода) — `advance` видит ход человека и оседает БЕЗ повторного дёрганья движка. Случай «два `advance` грузят одну до-движковую позицию и оба считают ход» (конкуррентная гонка) безопасен по **аргументу** детерминизма Rapfi (одинаковый ход → last-write-wins) — конкурентность детерминированно в юните не воспроизводится, поэтому это рассуждение, не тест.
> **Дедуп параллельных прогонов одной партии — `app.state.advancing`:** проверка `game_id in advancing` и `add` атомарны (между ними нет `await` — один поток asyncio). Конкуррентные `GET` на застрявшую → второй видит id в `advancing`, дубль не плодит; если первый уже снял id (партия осела) — второй `advance` грузит осевшую партию и тоже no-op. Durable-реестр in-flight (переживающий рестарт) — вне скоупа.
- [ ] **Step 4: Прогнать — PASS.**
- [ ] **Step 5: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): §4.8 — идемпотентный advance + чистые get_game/load (восстановление планирует роутер)"`.

---

## Task 10: DTO + роутер `/api/games` (create/list/get) + `/api/levels` + lifespan-проводка

**Files:** Create `app/game/dtos.py`, `app/routers/games.py`; Modify `app/app_factory.py`, `app/config.py`, `app/error_handlers.py`, `tests/conftest.py` (фикстура `games_api`); Test `tests/api/test_games_endpoints.py`.

- [ ] **Step 1: `app/config.py`** — добавить поле `sse_heartbeat_s: int = 15`.
- [ ] **Step 2: `app/game/dtos.py`**
```python
from pydantic import BaseModel


class OpponentBody(BaseModel):
    kind: str = "engine"
    levelId: str


class CreateGameBody(BaseModel):
    opponent: OpponentBody


class LevelDTO(BaseModel):
    id: str
    name: str
```
- [ ] **Step 3: `app/error_handlers.py`** — добавить handler для `MoveRejected`/`UndoRejected` (по `.reason`):
```python
# в register_error_handlers, после цикла _MAP:
    from app.domain.values import MoveRejected, MoveRejectReason, UndoRejected, UndoRejectReason

    def _rejected(_request, exc):
        reason = exc.reason
        opp = (reason is MoveRejectReason.OPPONENT_THINKING
               or reason is UndoRejectReason.OPPONENT_THINKING)
        return JSONResponse(status_code=409 if opp else 422,
                            content={"detail": reason.value})
    app.add_exception_handler(MoveRejected, _rejected)
    app.add_exception_handler(UndoRejected, _rejected)
```
- [ ] **Step 4: `app/app_factory.py`** — заменить тело `lifespan` (движок Rapfi + hub + levels + реестры фоновых задач; shutdown гасит фон, закрывает адаптер и engine):
```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.config import REPO_ROOT
        from app.game.event_hub import InMemoryEventHub
        from app.levels_config import load_levels
        from app.rapfi.adapter import RapfiAdapter

        engine = make_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        try:  # E1: НЕ сцеплять старт приложения с собранным бинарём (API-тесты подменят фейком)
            app.state.adapter = RapfiAdapter(  # как scripts/play_cli.py:62 — cwd=REPO_ROOT
                bin_path=settings.resolved_rapfi_bin(), config_path=settings.rapfi_config,
                cwd=REPO_ROOT, kill_grace_s=settings.engine_kill_grace_s)
        except FileNotFoundError:
            import logging
            logging.getLogger("renju").warning("Rapfi bin не собран — adapter=None")
            app.state.adapter = None
        app.state.event_hub = InMemoryEventHub()
        app.state.levels = {lv.id: lv for lv in load_levels(settings.levels_file)}  # id → LevelInfo
        app.state.bg_tasks = set()   # ссылки на фоновые advance-задачи (иначе GC оборвёт)
        app.state.advancing = set()  # game_id с активным фоновым advance (per-process дедуп)
        yield
        for t in list(app.state.bg_tasks):  # погасить незавершённые фоновые advance
            t.cancel()
        if app.state.adapter is not None:
            await app.state.adapter.close()
        await engine.dispose()
```
И `app.include_router(games_router.router)` (импорт сверху файла: `from app.routers import games as games_router`).

> **E1 (ревью 2026-06-12):** `resolved_rapfi_bin()` бросает `FileNotFoundError`, если движок не собран и `RENJU_RAPFI_BIN` не задан — иначе ВСЕ API-тесты (поднимают lifespan) требовали бы бинаря. Без бинаря → `adapter=None` (юнит-API ставят `FakeAdapter`; integration скипается фикстурой `rapfi_paths`). Прод деплоится с бинарём (RUNBOOK); `None` → фоновый `advance` залогирует и оставит `opponent_thinking` (см. `schedule_advance`). `advancing` — лёгкий per-process дедуп (множество `game_id`), НЕ durable-реестр (тот вне скоупа): пуст после рестарта, поэтому §4.8-восстановление при `GET` срабатывает само.
- [ ] **Step 5: `app/routers/games.py`** (create/list/get/levels; `current_user` из auth-роутера; `GameService` собирается per-request с session-репо)
```python
import asyncio
import logging
import random
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db.deps import get_session
from app.domain.values import GameStatus
from app.exceptions import BadInputError
from app.game.dtos import CreateGameBody, LevelDTO
from app.game.repository import SqlGameRepository
from app.game.service import GameService
from app.levels_config import resolve_level
from app.routers.auth import current_user

logger = logging.getLogger("renju.games")
router = APIRouter(prefix="/api", tags=["games"])


def _build_service(app, session: AsyncSession) -> GameService:
    levels = {lid: lv.params for lid, lv in app.state.levels.items()}
    return GameService(repo=SqlGameRepository(session), hub=app.state.event_hub,
                       adapter=app.state.adapter, levels=levels)


def _service(request: Request, session: AsyncSession) -> GameService:
    return _build_service(request.app, session)


def schedule_advance(app, game_id: str) -> None:
    """Фоновый прогон engine-ходов: СВОЯ сессия (request-сессия уже закрыта), свой
    GameService. Движок крутится только в advance, а advance — только здесь и в юнит-тестах.
    Дедуп по game_id (app.state.advancing): уже крутится → не плодим дубль. Идемпотентно (Task 9).
    Только ПЛАНИРУЕТ задачу (`create_task` не исполняет тело синхронно): между этим вызовом и
    последующим `_state`/`cursor` в эндпоинте нет `await`, поэтому cursor снимается ДО первого хода
    advance (спека §4.6: «cursor снять до advance»; реплей с этого cursor догонит события advance)."""
    if app.state.adapter is None:  # E1: движок не собран — фон бессмыслен (прод деплоится с бинарём)
        logger.warning("schedule_advance: adapter=None, game=%s остаётся opponent_thinking", game_id)
        return
    if game_id in app.state.advancing:  # уже есть активный фоновый advance на эту партию
        return
    app.state.advancing.add(game_id)

    async def _run() -> None:
        try:
            async with app.state.sessionmaker() as s:
                svc = _build_service(app, s)
                game = await svc.load(game_id)
                if game is not None:
                    await svc.advance(game)
        except Exception:
            logger.exception("background advance failed: game=%s", game_id)
        finally:
            app.state.advancing.discard(game_id)

    task = asyncio.create_task(_run())
    app.state.bg_tasks.add(task)
    task.add_done_callback(app.state.bg_tasks.discard)


def _public_controllers(controllers: dict) -> dict:  # id чужого игрока не светим
    return {side: ({"kind": "engine", "levelId": c["level_id"]} if c["kind"] == "engine"
                   else {"kind": "user"})
            for side, c in controllers.items()}


def _your_color(controllers: dict, user_id: int) -> str | None:
    for side, c in controllers.items():
        if c["kind"] == "user" and c["user_id"] == user_id:
            return side
    return None


def _state(game, user_id: int, hub) -> dict:
    fb = game.forbidden_log.get(str(len(game.moves)), [])
    return {"id": game.id, "owner_id": game.owner_id,
            "controllers": _public_controllers(game.controllers),
            "your_color": _your_color(game.controllers, user_id),
            "status": game.status, "moves": game.moves, "undo_count": game.undo_count,
            "cursor": hub.cursor(game.id), "forbidden": fb}


@router.get("/levels", response_model=list[LevelDTO])
async def levels(request: Request, _: Annotated[CurrentUser, Depends(current_user)]):
    return [LevelDTO(id=lv.id, name=lv.name) for lv in request.app.state.levels.values()]


@router.post("/games")
async def create_game(body: CreateGameBody, request: Request,
                      user: Annotated[CurrentUser, Depends(current_user)],
                      session: Annotated[AsyncSession, Depends(get_session)]):
    if body.opponent.kind != "engine":
        raise BadInputError("only engine opponent supported")
    if resolve_level(list(request.app.state.levels.values()), body.opponent.levelId) is None:
        raise BadInputError("unknown levelId")
    svc = _service(request, session)
    human = random.choice(["black", "white"])
    game = await svc.create_game(owner_id=user.user_id, opponent_level=body.opponent.levelId,
                                 human_color=human)
    if game.status == GameStatus.OPPONENT_THINKING.value:  # человек-чёрный → движок ходит 2-м в фоне
        schedule_advance(request.app, game.id)
    return _state(game, user.user_id, request.app.state.event_hub)


@router.get("/games")
async def list_games(request: Request, user: Annotated[CurrentUser, Depends(current_user)],
                     session: Annotated[AsyncSession, Depends(get_session)]):
    hub = request.app.state.event_hub
    return [_state(g, user.user_id, hub)
            for g in await _service(request, session).list_games(user.user_id)]


@router.get("/games/{game_id}")
async def get_game(game_id: str, request: Request,
                   user: Annotated[CurrentUser, Depends(current_user)],
                   session: Annotated[AsyncSession, Depends(get_session)]):
    game = await _service(request, session).get_game(game_id, user.user_id)
    if game.status == GameStatus.OPPONENT_THINKING.value:  # §4.8: застрявшая → доиграть фоном
        schedule_advance(request.app, game_id)
    return _state(game, user.user_id, request.app.state.event_hub)
```
- [ ] **Step 6: Общая фикстура `games_api` в `tests/conftest.py`** (корневой conftest — видна и `tests/api`, и `tests/integration`; `tests/` НЕ пакет, поэтому кросс-файловый импорт хелперов хрупок — даём фикстурой). `pytest` уже импортирован в этом conftest. Добавить:
```python
class _FakeAdapter:
    """Фейк-движок для юнит-API: ходит в ПЕРВУЮ свободную клетку зоны (без коллизий в advance)."""

    async def forbidden_points(self, moves):
        return []

    async def compute_move(self, moves, params, allowed_zone=None):
        occupied = {tuple(m) for m in moves}
        cells = sorted(allowed_zone) if allowed_zone else [
            (x, y) for x in range(15) for y in range(15)]
        for c in cells:
            if tuple(c) not in occupied:
                return tuple(c)
        raise AssertionError("board full")

    async def close(self):
        pass


@pytest.fixture
def games_api():
    """Хелперы игровых API-тестов: FakeAdapter, seed_login, wait_settled, free_move."""
    import asyncio as _aio
    from types import SimpleNamespace

    from app.domain.opening import opening_zone

    async def seed_login(app, client, username="alice"):
        from app.dal import users as dal
        async with app.state.sessionmaker() as s:
            if not await dal.get_user_by_username(s, username):
                await dal.create_user(s, username, "pw")
                await s.commit()
        await client.post("/api/auth/login", json={"username": username, "password": "pw"})

    async def wait_settled(client, gid, tries=100, delay=0.02):
        """Поллить GET, пока партия не уйдёт из opponent_thinking (фоновый advance осел)."""
        st = (await client.get(f"/api/games/{gid}")).json()
        for _ in range(tries):
            if st["status"] != "opponent_thinking":
                return st
            await _aio.sleep(delay)
            st = (await client.get(f"/api/games/{gid}")).json()
        return st

    def free_move(state):
        """Свободная ЛЕГАЛЬНАЯ клетка текущей дебютной зоны (с учётом фолов из state)."""
        occupied = {tuple(m) for m in state["moves"]}
        forbidden = {tuple(p) for p in state.get("forbidden", [])}
        zone = opening_zone(len(state["moves"]))
        cells = sorted(zone) if zone else [(x, y) for x in range(15) for y in range(15)]
        for c in cells:
            if c not in occupied and c not in forbidden:
                return c
        raise AssertionError("no free legal cell")

    return SimpleNamespace(FakeAdapter=_FakeAdapter, seed_login=seed_login,
                           wait_settled=wait_settled, free_move=free_move)
```
- [ ] **Step 7: Тесты** `tests/api/test_games_endpoints.py`
```python
async def test_create_and_get_game(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()  # подмена живого движка на фейк
    await games_api.seed_login(app, client)
    r = await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    assert r.status_code == 200
    body = r.json()
    assert "your_color" in body and "cursor" in body
    assert body["status"] in ("awaiting_move", "opponent_thinking")
    st = await games_api.wait_settled(client, body["id"])  # дождаться возможного хода движка
    assert st["status"] == "awaiting_move" and st["id"] == body["id"]


async def test_games_require_auth(client):
    assert (await client.post("/api/games",
            json={"opponent": {"kind": "engine", "levelId": "master"}})).status_code == 401


async def test_levels_endpoint(app, client, games_api):
    await games_api.seed_login(app, client)
    r = await client.get("/api/levels")
    assert r.status_code == 200 and any(lv["id"] == "master" for lv in r.json())


async def test_create_unknown_level_400(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    r = await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "nope"}})
    assert r.status_code == 400  # BadInputError→400 (единая модель ошибок среза 1; спека §4.6 выровнена на 400)
```
> `app`-фикстура поднимает lifespan → конструирует живой `RapfiAdapter` (или `None`, если бинаря нет — E1); в юнит-API подменяем `app.state.adapter = games_api.FakeAdapter()` сразу после старта. Фоновый advance планируется на event-loop теста; `wait_settled` (через `await client.get` + `sleep`) даёт ему отработать. Живой движок — Task 13.
- [ ] **Step 8: Прогнать — PASS.** `uv run pytest tests/api/test_games_endpoints.py -v` + полный `uv run pytest -q`.
- [ ] **Step 9: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): /api/games (create/list/get) + /api/levels + движок/hub/levels в lifespan + фоновый advance"`.

---

## Task 11: move/undo эндпоинты

**Files:** Modify `app/routers/games.py`; Test `tests/api/test_games_endpoints.py`.

- [ ] **Step 1: Тесты (red)** — добавить (хелперы из фикстуры `games_api`, Task 10):
```python
async def test_move_then_undo(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (await client.post("/api/games",
           json={"opponent": {"kind": "engine", "levelId": "master"}})).json()["id"]
    st = await games_api.wait_settled(client, gid)  # осесть на ходу человека
    assert st["status"] == "awaiting_move"
    pt = games_api.free_move(st)
    mv = await client.post(f"/api/games/{gid}/move", json={"x": pt[0], "y": pt[1]})
    assert mv.status_code == 202
    st = await games_api.wait_settled(client, gid)  # дождаться фонового ответа движка
    assert st["status"] == "awaiting_move" and len(st["moves"]) >= 3
    un = await client.post(f"/api/games/{gid}/undo")  # после реального хода есть что откатывать
    assert un.status_code == 200 and len(un.json()["moves"]) < len(st["moves"])


async def test_move_occupied_422(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (await client.post("/api/games",
           json={"opponent": {"kind": "engine", "levelId": "master"}})).json()["id"]
    await games_api.wait_settled(client, gid)
    r = await client.post(f"/api/games/{gid}/move", json={"x": 7, "y": 7})  # центр занят → OCCUPIED
    assert r.status_code == 422


async def test_move_when_opponent_thinking_409(app, client, games_api):
    from app.models.game import Game
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (await client.post("/api/games",
           json={"opponent": {"kind": "engine", "levelId": "master"}})).json()["id"]
    await games_api.wait_settled(client, gid)
    # детерминированно загнать в opponent_thinking (как будто соперник думает); без GET — фон не планируем
    async with app.state.sessionmaker() as s:
        g = await s.get(Game, gid)
        g.status = "opponent_thinking"
        await s.commit()
    r = await client.post(f"/api/games/{gid}/move", json={"x": 6, "y": 6})
    assert r.status_code == 409  # MoveRejected(OPPONENT_THINKING) → 409
```
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: Добавить в `app/routers/games.py`**
```python
from pydantic import BaseModel


class MoveBody(BaseModel):
    x: int
    y: int


@router.post("/games/{game_id}/move", status_code=202)
async def move(game_id: str, body: MoveBody, request: Request,
               user: Annotated[CurrentUser, Depends(current_user)],
               session: Annotated[AsyncSession, Depends(get_session)]):
    game = await _service(request, session).submit_move(game_id, user.user_id, (body.x, body.y))
    if game.status == GameStatus.OPPONENT_THINKING.value:  # ход соперника-движка — в фоне
        schedule_advance(request.app, game_id)
    return {"accepted": True}  # 202: ход принят; ответ соперника придёт SSE-событием


@router.post("/games/{game_id}/undo")
async def undo(game_id: str, request: Request,
               user: Annotated[CurrentUser, Depends(current_user)],
               session: Annotated[AsyncSession, Depends(get_session)]):
    game = await _service(request, session).undo(game_id, user.user_id)
    return _state(game, user.user_id, request.app.state.event_hub)
```
- [ ] **Step 4: Прогнать — PASS.** `uv run pytest tests/api/test_games_endpoints.py -v`.
- [ ] **Step 5: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): POST /api/games/{id}/move (202) + /undo"`.

---

## Task 12: SSE-эндпоинт `/api/games/{id}/events`

**Files:** Modify `app/routers/games.py`; Test `tests/api/test_games_sse.py`.

- [ ] **Step 1: Тест (red)** `tests/api/test_games_sse.py` — подписка отдаёт события, накопленные при создании (человек чёрный → движок сходил → есть `move`/`status`):
```python
async def test_sse_replays_buffered_events(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (await client.post("/api/games",
           json={"opponent": {"kind": "engine", "levelId": "master"}})).json()["id"]
    st = await games_api.wait_settled(client, gid)
    # гарантируем события в буфере хаба: подаём ход → фоновый advance публикует move/status
    pt = games_api.free_move(st)
    await client.post(f"/api/games/{gid}/move", json={"x": pt[0], "y": pt[1]})
    await games_api.wait_settled(client, gid)
    # реплей с курсора 0 отдаёт накопленные из буфера события (без ожидания live)
    got = []
    async with client.stream("GET", f"/api/games/{gid}/events?since=0") as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                got.append(line)
                break
    assert got  # хотя бы одно событие (move/status) из буфера
```
> SSE-тест чувствителен к таймингам — держим минимальным (одно событие из буфера). Idle→`ping`-механизм покрыт детерминированно на уровне хаба (`test_subscribe_heartbeat_ping_on_idle`, Task 5), здесь его НЕ дублируем (флак).
- [ ] **Step 2: Прогнать — FAIL.**
- [ ] **Step 3: Добавить в `app/routers/games.py`**
```python
import json as _json
from fastapi.responses import StreamingResponse

from app.auth import decode_token, fetch_token_epoch, get_current_user


@router.get("/games/{game_id}/events")
async def events(game_id: str, request: Request, since: int = 0):
    # SSE — долгоживущий стрим: НЕ берём Depends(current_user)/Depends(get_session)
    # (они держали бы request-сессию открытой весь стрим). Auth+доступ — на КОРОТКОЙ сессии.
    hub = request.app.state.event_hub
    sm = request.app.state.sessionmaker
    settings = request.app.state.settings
    async with sm() as s0:
        user = await get_current_user(request, s0, settings)  # нет cookie/отозван → AuthError→401
        game = await _service(request, s0).get_game(game_id, user.user_id)  # 404 если нет доступа
    if game.status == GameStatus.OPPONENT_THINKING.value:  # §4.8: застрявшая → доиграть фоном
        schedule_advance(request.app, game_id)
    jwt_epoch = decode_token(request.cookies[settings.cookie_name], settings).get("tep", 0)

    async def gen():
        # heartbeat живёт ВНУТРИ subscribe (idle_timeout) — НЕ оборачиваем __anext__ снаружи (B-2)
        async for ev in hub.subscribe(game_id, since, idle_timeout=settings.sse_heartbeat_s):
            if ev["type"] == "ping":
                async with sm() as s2:  # epoch-recheck на свежей короткой сессии
                    cur = await fetch_token_epoch(s2, user.user_id)
                if cur is None or cur != jwt_epoch:
                    return  # сессия отозвана — закрыть стрим
                yield ": ping\n\n"
            else:  # data = весь объект события {seq, type, payload} (спека §«Контракт SSE», N-2)
                yield f"event: {ev['type']}\ndata: {_json.dumps(ev)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})
```
> SSE не использует `Depends(current_user)`/`get_session` — иначе request-сессия висит весь долгоживущий стрим (нарушение спеки + лизинг коннекта). Auth и проверка доступа — внутри тела на короткой `sm()`-сессии (`get_current_user` сам бросит `AuthError`→401 при отсутствии cookie/отзыве). **Heartbeat — внутри `subscribe(idle_timeout=…)`** (B-2: обёртка `__anext__` снаружи закрыла бы генератор на первом таймауте); на каждый `ping` — epoch-recheck отдельной короткой сессией. `asyncio` уже импортирован сверху роутера (Task 10).
> **Точность отзыва (честно):** epoch-recheck срабатывает на heartbeat (idle), значит на АКТИВНОЙ партии (события идут чаще `sse_heartbeat_s`) `q.get()` не таймаутит, `ping` не возникает, и отозванная сессия продолжает получать live-поток, **пока партия не затихнет** — окно ограничено не интервалом heartbeat, а паузой в событиях. Это сознательно: мгновенный teardown-реестр на бампе epoch отложен (спека §4.4 «достаточно перепроверки на heartbeat»). Не утверждать «отозван → сразу закрыли».
> **Интеракция с refresh-middleware (безвредна):** `get_current_user` при близком к истечению токене ставит `request.state.refresh`; `add_refresh` (срез 1) после `call_next` ставит cookie на `StreamingResponse` — заголовки ещё не отправлены (тело не начало стримиться), set_cookie применяется корректно: один refresh cookie при открытии стрима. Отдельным тестом не покрыто (тонкая интеграция Starlette), на контракт среза не влияет.
- [ ] **Step 4: Прогнать — PASS** (тест минимальный, по таймауту). Если флак — увеличить окно/упростить. Полный `uv run pytest -q`.
- [ ] **Step 5: Линт/тип/коммит.** `git commit -m "feat(rj-5c9): SSE /api/games/{id}/events (реплей+heartbeat+epoch-recheck)"`.

---

## Task 13: Integration против живого движка + smoke

**Files:** Create `tests/integration/test_games_live.py`; ручной smoke.

- [ ] **Step 1: Integration-тест** (живой движок; скип если бинарь не собран — фикстура `rapfi_paths` из conftest)
```python
async def test_create_and_move_live_engine(app, client, games_api, rapfi_paths):
    # app поднял живой RapfiAdapter в lifespan — НЕ подменяем (rapfi_paths скипает без бинаря)
    await games_api.seed_login(app, client)
    gid = (await client.post("/api/games",
           json={"opponent": {"kind": "engine", "levelId": "novice"}})).json()["id"]
    # человек мог выпасть чёрным → первый ход за движком в фоне; ждём оседания (живой движок ~секунды)
    st = await games_api.wait_settled(client, gid, tries=120, delay=0.25)
    assert st["status"] == "awaiting_move"
    n0 = len(st["moves"])
    pt = games_api.free_move(st)  # свободная легальная клетка зоны (с учётом реальных фолов)
    await client.post(f"/api/games/{gid}/move", json={"x": pt[0], "y": pt[1]})
    st = await games_api.wait_settled(client, gid, tries=120, delay=0.25)  # реальный ответ движка
    assert len(st["moves"]) >= n0 + 2 or st["status"].startswith("finished")
```
> **Последовательно** (shared Rapfi). `wait_settled(tries=120, delay=0.25)` ≈ 30 с бюджета на ход живого движка (первый дольше — ленивая загрузка весов). `free_move` берёт легальную клетку зоны с учётом фолов из `state["forbidden"]`. Ход человека (+1) и ответ движка (+1) → `n0+2`.
- [ ] **Step 2: Прогнать.** `uv run pytest tests/integration/test_games_live.py -v` (требует собранного движка).
- [ ] **Step 3: Ручной smoke (Alexey-делегировано — я сам):**
```bash
RENJU_DATA_DIR=/tmp/renju-s2 uv run alembic upgrade head
RENJU_DATA_DIR=/tmp/renju-s2 uv run python -m scripts.create_admin root pw
RENJU_DATA_DIR=/tmp/renju-s2 uv run uvicorn app.app_factory:create_app --factory --port 8099
# curl: login → создать игру → GET → move → (SSE) увидеть ход движка событием → undo
```
> **Покрытие SSE (решение по находке ревью Task 12, MINOR 2):** логика `gen()`→`subscribe`→реплей-из-буфера покрыта юнитом (`test_sse_replays_buffered_events`, прямой вызов хендлера — `httpx.ASGITransport` буферизует тело и на бесконечном стриме виснет); heartbeat-ping — юнитом хаба (`test_subscribe_heartbeat_ping_on_idle`, T5); проводка auth/доступ-отказа (401/404) — юнит-assertion'ами (`pytest.raises(AuthError|NotFoundError)`, добавлены по MINOR 1). **Реальный HTTP-провод SSE** (стриминг через сокет + middleware) покрыт **ручным curl-smoke** выше. Авто-тест SSE на живом uvicorn-сокете НЕ добавляем: threaded-uvicorn с кросс-loop координацией в async-pytest — непропорциональная инфра для self-hosted MVP; если SSE-регрессии станут болью — отдельный тикет.
- [ ] **Step 4: Полный прогон + линт + тип.** `uv run pytest -q` · `uv run ruff check app tests scripts && uv run ruff format app tests scripts` · `uvx pyright` (0 errors).
- [ ] **Step 5: Коммит** `git commit -m "test(rj-5c9): integration против живого движка"`.

---

## Self-Review (проведено)

- **Покрытие спеки:** статус-rename rj-8sc (T1) · games-таблица+миграция (T2) · контролёры/Player/фабрика (T3) · GameRepository SQLite+in-memory (T4) · EventHub (T5) · fouls-мемо (T6) · advance+нейтральность (T7) · submit/undo-replay (T8) · §4.8-восстановление (T9) · /api/games+levels+lifespan (T10) · move/undo-эндпоинты (T11) · SSE+epoch (T12) · integration+smoke (T13). Все разделы спеки имеют задачу.
- **Фоновый `advance` (спека §4.6, решение Alexey 2026-06-12 «фон, единообразно»):** движок крутится ТОЛЬКО в `advance`, а `advance` — ТОЛЬКО в фоновой задаче роутера (`schedule_advance`, своя сессия) и в юнит-тестах. `create_game`/`submit_move` применяют ход человека, ставят статус позиционно (`_next_status`), коммитят и возвращают сразу; `opponent_thinking` → роутер планирует фон; ответ соперника приходит SSE. Механика «движок vs человек» спрятана единообразно. Дедуп фоновых прогонов — `app.state.advancing` (per-process), §4.8-восстановление при `GET`/SSE планирует тот же фон.
- **forbidden_log:** dict по `str(len)`, мемо в `fouls`, undo выбрасывает ключи `>k`, движок только в `advance` — сквозно (T6/T7/T8).
- **Коммит-модель:** писатели (`SqlGameRepository.create/update`) коммитят явно; читатели — нет. Сервис переприсваивает JSON-колонки (`game.moves=[...]`, `game.forbidden_log={...}`).
- **Нейтральность:** `advance` через фасад `Player`; тест PvP-формы (не ходит) + HvE (ходит).
- **Типы/имена:** `GameService(repo,hub,adapter,levels)`, `Player.take_turn`, `controller_from_json/to_json`, `fouls/advance/submit_move/undo/get_game/load/list_games/create_game/_next_status` — согласованы между задачами.
- **Findings ревью 2026-06-12 (закрыты в плане):** M1 — `advance` фоновый (не inline); B1 — undo-тест по человеку-белому (preset-floor чёрного обходит `NOTHING_TO_UNDO`); B2 — `NOT_YOUR_TURN` тестируем PvP-формой (+ чужой `user_id`→`NotFoundError`); B3 — rename меняет и символы, и строковые литералы/имена тестов; E1 — lifespan-адаптер E1-tolerant (`FileNotFoundError`→`None`), API-тесты не требуют бинаря.
- **Без плейсхолдеров:** код в шагах полный.

## Что НЕ в этом плане (scope — не предлагать как findings)

- durable `sse_events` (реплей через рестарт), мгновенный teardown-реестр SSE на бампе epoch — отдельный тикет (решение A). Сюда же — **реклейм/эвикция `EventHub`-буфера**: in-memory `_log`/`_seq`/`_subs` по завершённым партиям не освобождаются (на партию буфер ограничен ≤ пары сотен событий — спека §«Контракт SSE», но между партиями копится при долгоживущем процессе). Для MVP приемлемо; вытеснение/TTL едут с durable-impl.
- PvP-матчмейкинг (opponent `kind:"user"`), per-user undo-настройки (`/settings`), фронт.
- Калибровка уровней, admin engine-config.
