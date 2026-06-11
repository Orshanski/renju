# User + Auth Foundation (срез 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Поднять фундамент этапа 2 — FastAPI-каркас, БД (SQLAlchemy async + Alembic), модель `User` и авторизацию (JWT-cookie + `token_epoch`), перенеся проверенные алгоритмы из librarium на ORM.

**Architecture:** Слоистый бэкенд (§4.9): роутеры тонкие → сервисы оркеструют → DAL единственный к БД (async ORM) → `app/auth.py` крипто+зависимость. `token_epoch`-отзыв сессий читается из БД на каждом запросе (без in-memory кеша — у renju нет authed-fan-out, обоснование в спеке). Security-заголовки ставит само приложение (middleware), не nginx. Источник переноса — `/Users/alexey/code/librarium-py/backend/app/`.

**Tech Stack:** Python 3.13 / uv / FastAPI / SQLAlchemy 2.0 async + aiosqlite / Alembic / PyJWT / bcrypt / pytest (asyncio_mode=auto) + httpx.AsyncClient. bd: `rj-a4k`.

**Спека:** `docs/superpowers/specs/2026-06-11-user-auth-foundation-design.md`.

**Команды:** из `backend/`. `uv run pytest -q` · `uv run pytest tests/unit/test_x.py::test_y -v` · `uv run ruff check app tests scripts && uv run ruff format app tests scripts`. **Pytest последовательно** (shared state). После каждой задачи — линт + коммит.

---

## File Structure

- `app/config.py` (**править**) — добавить auth/БД-поля в `Settings`.
- `app/db/base.py` (создать) — `DeclarativeBase`.
- `app/db/engine.py` (создать) — async engine + PRAGMA на `sync_engine`.
- `app/db/session.py` (создать) — зависимость `get_session()`.
- `app/models/user.py` (создать) — ORM-модель `User`.
- `app/auth.py` (создать) — bcrypt, JWT, `CurrentUser`, `get_current_user`, `require_admin`, `bump_token_epoch`, refresh.
- `app/dal/users.py` (создать) — ORM-запросы по users.
- `app/dtos/auth.py` (создать) — pydantic DTO.
- `app/exceptions.py` (создать) — доменные исключения.
- `app/error_handlers.py` (создать) — регистрация маппинга класс→статус.
- `app/services/auth_service.py` (создать) — login + rate-limit, get_me.
- `app/services/admin_service.py` (создать) — user CRUD + guards.
- `app/routers/auth.py` (создать) — `/api/auth/*`.
- `app/routers/admin.py` (создать) — `/api/admin/users/*`.
- `app/middleware/security_headers.py`, `csrf.py`, `refresh.py` (создать).
- `app/app_factory.py` (создать) — `create_app()`: lifespan, middlewares, роутеры, `/api/health`.
- `alembic/` + `alembic.ini` (создать) — миграции; первая ревизия — `users`.
- `scripts/create_admin.py` (создать) — CLI bootstrap.
- `tests/conftest.py` (**править**) — async-фикстуры: engine/session/AsyncClient на временной БД.
- `tests/unit/test_*.py`, `tests/api/test_*.py` (создать) — тесты по задачам.

**Вне скоупа (срез 2 / не трогать):** игровой контур, движок Rapfi в lifespan, SSE/EventHub, `user_settings`, PUT-смена-роли, фронт. Существующие `app/domain`, `app/rapfi`, `app/game_service.py` — не трогаем.

---

## Task 1: Зависимости + конфиг

**Files:**
- Modify: `pyproject.toml` (через `uv add`), `app/config.py`
- Test: `tests/unit/test_config.py` (дополнить)

- [ ] **Step 1: Добавить зависимости**

```bash
uv add sqlalchemy aiosqlite alembic pyjwt bcrypt
uv add --dev httpx
```
Expected: `uv.lock` обновлён, `uv sync` проходит.

- [ ] **Step 2: Тест на новые поля конфига (red)**

В `tests/unit/test_config.py` добавить:
```python
def test_settings_auth_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    from app.config import Settings
    s = Settings()
    assert s.data_dir == tmp_path
    assert s.db_path == tmp_path / "db.sqlite"
    assert s.jwt_algorithm == "HS256"
    assert s.jwt_expire_hours == 168
    assert s.cookie_name == "renju_token"
    assert s.secure_cookie is False
```

- [ ] **Step 3: Прогнать — FAIL** (`AttributeError`/нет полей). Run: `uv run pytest tests/unit/test_config.py::test_settings_auth_defaults -v`.

- [ ] **Step 4: Расширить `Settings`**

В `app/config.py` добавить в класс `Settings` (после существующих полей), и импорт `import secrets`, `from functools import cached_property`:
```python
    data_dir: Path = REPO_ROOT / "data"  # RENJU_DATA_DIR; в тестах переопределяется
    db_path: Path | None = None  # дефолт data_dir/db.sqlite (см. resolved_db_path)
    secret_key: str | None = None  # RENJU_SECRET_KEY; иначе генерится в data_dir/.secret_key
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 168  # 7 дней
    jwt_refresh_after_hours: int = 84  # половина TTL
    cookie_name: str = "renju_token"
    secure_cookie: bool = False  # RENJU_SECURE_COOKIE
    busy_timeout_ms: int = 5000
```
И методы:
```python
    @property
    def resolved_db_path(self) -> Path:
        return self.db_path if self.db_path is not None else self.data_dir / "db.sqlite"

    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        f = self.data_dir / ".secret_key"
        if f.exists():
            return f.read_text().strip()
        key = secrets.token_hex(32)
        f.write_text(key)
        f.chmod(0o600)
        return key
```
> Примечание: для теста Step 2 поле `db_path` остаётся `None`, а `resolved_db_path` даёт `data_dir/db.sqlite`. Заменить в тесте `s.db_path` на `s.resolved_db_path`.

- [ ] **Step 5: Поправить тест на `resolved_db_path`, прогнать — PASS.** Run: `uv run pytest tests/unit/test_config.py -v`.

- [ ] **Step 6: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add pyproject.toml uv.lock app/config.py tests/unit/test_config.py
git commit -m "feat(rj-a4k): зависимости БД/auth + поля конфига (data_dir/jwt/cookie)"
```

---

## Task 2: БД-слой + тест-фикстуры

**Files:**
- Create: `app/db/__init__.py`, `app/db/base.py`, `app/db/engine.py`, `app/db/session.py`
- Modify: `tests/conftest.py`
- Test: `tests/unit/test_db_session.py`

- [ ] **Step 1: `app/db/base.py`**
```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2: `app/db/engine.py`**
```python
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{settings.resolved_db_path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _record):  # PRAGMA на sync_engine — иначе не подключится
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute(f"PRAGMA busy_timeout={settings.busy_timeout_ms}")
        cur.close()

    return engine
```

- [ ] **Step 3: `app/db/session.py`**
```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def make_sessionmaker(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(sm: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Только rollback-on-error + close. Коммит — ЯВНО в сервисах записи.
    Почему не авто-commit: SQLAlchemy autobegin открывает транзакцию на ЛЮБОМ
    SELECT, поэтому `session.in_transaction()` True и для read-only — отличить
    «были изменения» так нельзя; а DAL делает flush() (после него session.dirty/new
    пусты). Надёжная модель: писатели (admin_service.*) коммитят сами, читатели
    (get_current_user, get_me, list_users) не коммитят вовсе → ноль лишних fsync на GET."""
    session = sm()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
```
> `get_session` как FastAPI-зависимость собирается в `app_factory` (Task 9) поверх `session_scope` + app-state sessionmaker. Здесь — переиспользуемое ядро. **Модель коммитов:** запись коммитит сервис (`await session.commit()` в конце мутирующего метода), чтение — никогда.

- [ ] **Step 4: Фикстуры в `tests/conftest.py`**

Добавить (не ломая существующее):
```python
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

@pytest_asyncio.fixture
async def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    from app.config import Settings
    from app.db.engine import make_engine
    from app.db.base import Base
    import app.models.user  # noqa: F401 — регистрирует таблицу в metadata
    eng = make_engine(Settings())
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()

@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    from app.db.session import make_sessionmaker
    sm = make_sessionmaker(engine)
    async with sm() as s:
        yield s
```

- [ ] **Step 5: Тест сессии (red→green)** `tests/unit/test_db_session.py`
```python
from sqlalchemy import text

async def test_pragmas_applied(session):
    assert (await session.execute(text("PRAGMA foreign_keys"))).scalar() == 1
    assert (await session.execute(text("PRAGMA journal_mode"))).scalar().lower() == "wal"
```
Run: `uv run pytest tests/unit/test_db_session.py -v` (требует Task 3 для `app.models.user`; если ещё нет — закоммить Task 2 кодом, тест включить в Task 3). Expected после Task 3: PASS.

- [ ] **Step 6: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/db tests/conftest.py
git commit -m "feat(rj-a4k): async-движок БД (WAL/FK pragmas на sync_engine) + сессия + тест-фикстуры"
```

---

## Task 3: Модель User + Alembic + первая миграция

**Files:**
- Create: `app/models/__init__.py`, `app/models/user.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_users.py`
- Test: `tests/unit/test_db_session.py` (включить), `tests/unit/test_migration.py`

- [ ] **Step 1: `app/models/user.py`**
```python
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(default="user")  # 'admin' | 'user'
    token_epoch: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.current_timestamp())
```

- [ ] **Step 2: Прогнать тест сессии из Task 2** (теперь `app.models.user` есть). Run: `uv run pytest tests/unit/test_db_session.py -v`. Expected: PASS.

- [ ] **Step 3: Инициализировать Alembic**
```bash
uv run alembic init -t async alembic
```
Expected: создан `alembic/` (async-шаблон) + `alembic.ini`.

- [ ] **Step 4: Настроить `alembic/env.py`**

Заменить целевую метадату и URL на наши: вверху `env.py` добавить
```python
from app.config import Settings
from app.db.base import Base
import app.models.user  # noqa: F401
target_metadata = Base.metadata
_settings = Settings()
config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{_settings.resolved_db_path}")
```
(async-шаблон уже содержит `run_async_migrations` + `connection.run_sync(do_run_migrations)` — не трогаем его.)

- [ ] **Step 5: Сгенерировать миграцию users**
```bash
uv run alembic revision --autogenerate -m "users"
```
Проверить, что в `alembic/versions/*_users.py` создаётся таблица `users` с колонками id/username(unique)/password_hash/role(default 'user')/token_epoch(default 0)/created_at. При необходимости поправить вручную (autogenerate под SQLite иногда пропускает server_default).

- [ ] **Step 6: Тест миграции** `tests/unit/test_migration.py`
```python
import subprocess
from sqlalchemy import create_engine, inspect

def test_alembic_upgrade_creates_users(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    assert {"id", "username", "password_hash", "role", "token_epoch", "created_at"} <= cols
    eng.dispose()
```
Run: `uv run pytest tests/unit/test_migration.py -v`. Expected: PASS.

- [ ] **Step 7: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/models alembic.ini alembic tests/unit/test_migration.py tests/unit/test_db_session.py
git commit -m "feat(rj-a4k): модель User + Alembic (async) + миграция users"
```

---

## Task 4: Auth-примитивы (bcrypt, JWT, CurrentUser) — pure

**Files:**
- Create: `app/auth.py` (часть 1 — без БД-зависимостей)
- Test: `tests/unit/test_auth_primitives.py`

- [ ] **Step 1: Тесты (red)** `tests/unit/test_auth_primitives.py`
```python
import pytest
from app.auth import (hash_password, verify_password, create_token, decode_token,
                      CurrentUser, AuthError)
from app.config import Settings


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))  # секрет в tmp, не в репо
    return Settings()

def test_password_roundtrip():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)

def test_token_roundtrip(cfg):
    t = create_token(user_id=7, role="admin", token_epoch=3, settings=cfg)
    p = decode_token(t, cfg)
    assert p["userId"] == 7 and p["role"] == "admin" and p["tep"] == 3
    assert isinstance(p["iat"], (int, float))  # PyJWT декодирует iat как unix-timestamp

def test_decode_tampered_raises(cfg):
    with pytest.raises(Exception):
        decode_token("not.a.jwt", cfg)

def test_current_user_from_payload_ok():
    u = CurrentUser.from_payload({"userId": 7, "role": "admin"})
    assert u.user_id == 7 and u.role == "admin"

@pytest.mark.parametrize("bad", [{"role": "user"}, {"userId": True, "role": "u"},
                                 {"userId": 1}, {"userId": 1, "role": ""}])
def test_current_user_from_payload_rejects(bad):
    with pytest.raises(AuthError):
        CurrentUser.from_payload(bad)
```

- [ ] **Step 2: Прогнать — FAIL** (нет `app.auth`). Run: `uv run pytest tests/unit/test_auth_primitives.py -v`.

- [ ] **Step 3: `app/auth.py` (часть 1)**
```python
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import Settings

log = logging.getLogger("renju.auth")
_INVALID = "Invalid token"
# ЗАПРЕТ module-level Settings(): модуль импортируется ОДИН раз → frozen Settings
# проигнорирует monkeypatch.setenv в тестах. Settings приходит ПАРАМЕТРОМ (из
# app.state.settings в роутерах/мидлварах; напрямую в юнит-тестах).


class AuthError(Exception):
    """Нет/невалидный токен или креды. → 401."""


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int, role: str, token_epoch: int, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {"userId": user_id, "role": role, "tep": token_epoch,
               "iat": now, "exp": now + timedelta(hours=settings.jwt_expire_hours)}
    return jwt.encode(payload, settings.resolved_secret_key(), algorithm=settings.jwt_algorithm)


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    return jwt.decode(token, settings.resolved_secret_key(), algorithms=[settings.jwt_algorithm])


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    role: str

    @classmethod
    def from_payload(cls, p: dict[str, Any]) -> "CurrentUser":
        uid = p.get("userId")
        # bool — подкласс int; без этой проверки True прошёл бы как int
        if isinstance(uid, bool) or not isinstance(uid, int):
            log.warning("JWT malformed: userId")
            raise AuthError(_INVALID)
        role = p.get("role")
        if not isinstance(role, str) or not role:
            log.warning("JWT malformed: role")
            raise AuthError(_INVALID)
        return cls(user_id=uid, role=role)
```

- [ ] **Step 4: Прогнать — PASS.** Run: `uv run pytest tests/unit/test_auth_primitives.py -v`.

- [ ] **Step 5: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/auth.py tests/unit/test_auth_primitives.py
git commit -m "feat(rj-a4k): auth-примитивы — bcrypt, JWT, CurrentUser (перенос librarium)"
```

---

## Task 5: DAL users + bump_token_epoch

**Files:**
- Create: `app/dal/__init__.py`, `app/dal/users.py`
- Modify: `app/auth.py` (добавить `bump_token_epoch`, `fetch_token_epoch`)
- Test: `tests/unit/test_dal_users.py`

- [ ] **Step 1: Тесты (red)** `tests/unit/test_dal_users.py`
```python
from app.dal import users as dal
from app.auth import bump_token_epoch, fetch_token_epoch

async def test_create_and_get(session):
    uid = await dal.create_user(session, "alice", "pw", role="admin")
    await session.commit()
    u = await dal.get_user_by_username(session, "alice")
    assert u.id == uid and u.role == "admin" and u.password_hash != "pw"

async def test_is_last_admin(session):
    a = await dal.create_user(session, "a", "pw", role="admin")
    await session.commit()
    assert await dal.is_last_admin(session, a) is True
    await dal.create_user(session, "b", "pw", role="admin")
    await session.commit()
    assert await dal.is_last_admin(session, a) is False

async def test_bump_epoch(session):
    uid = await dal.create_user(session, "alice", "pw")
    await session.commit()
    assert await fetch_token_epoch(session, uid) == 0
    assert await bump_token_epoch(session, uid) == 1
    await session.commit()
    assert await fetch_token_epoch(session, uid) == 1
    assert await bump_token_epoch(session, 999) is None  # нет строки
```

- [ ] **Step 2: Прогнать — FAIL.** Run: `uv run pytest tests/unit/test_dal_users.py -v`.

- [ ] **Step 3: `app/dal/users.py`**
```python
from sqlalchemy import func, select

from app.auth import hash_password
from app.models.user import User


async def get_user_by_id(session, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_username(session, username: str) -> User | None:
    return (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()


async def list_users(session) -> list[User]:
    return list((await session.execute(select(User).order_by(User.id))).scalars())


async def create_user(session, username: str, password: str, role: str = "user") -> int:
    user = User(username=username, password_hash=hash_password(password), role=role)
    session.add(user)
    await session.flush()  # получить id без commit (commit — зона сервиса/сессии)
    return user.id


async def delete_user(session, user_id: int) -> None:
    user = await session.get(User, user_id)
    if user is not None:
        await session.delete(user)


async def count_admins(session) -> int:
    return (await session.execute(
        select(func.count()).select_from(User).where(User.role == "admin"))).scalar_one()


async def is_last_admin(session, user_id: int) -> bool:
    user = await session.get(User, user_id)
    if user is None or user.role != "admin":
        return False
    return await count_admins(session) <= 1
```

- [ ] **Step 4: Добавить в `app/auth.py`**
```python
from sqlalchemy import update
from app.models.user import User


async def fetch_token_epoch(session, user_id: int) -> int | None:
    return await session.scalar(select(User.token_epoch).where(User.id == user_id))


async def bump_token_epoch(session, user_id: int) -> int | None:
    """UPDATE … RETURNING; новый epoch или None если строки нет (guard на гонку reset×delete)."""
    return await session.scalar(
        update(User).where(User.id == user_id)
        .values(token_epoch=User.token_epoch + 1)
        .returning(User.token_epoch)
    )
```
(добавить импорт `from sqlalchemy import select, update` в `app/auth.py`.)

- [ ] **Step 5: Прогнать — PASS.** Run: `uv run pytest tests/unit/test_dal_users.py -v`.

- [ ] **Step 6: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/dal app/auth.py tests/unit/test_dal_users.py
git commit -m "feat(rj-a4k): DAL users (ORM) + bump/fetch token_epoch (RETURNING-guard)"
```

---

## Task 6: Исключения + error_handlers

**Files:**
- Create: `app/exceptions.py`, `app/error_handlers.py`
- Test: `tests/api/test_error_handlers.py` (+ `tests/api/__init__.py`)

- [ ] **Step 1: `app/exceptions.py`**
```python
class BadInputError(ValueError):
    """→ 400."""

class NotFoundError(LookupError):
    """→ 404."""

class ConflictError(FileExistsError):
    """→ 409."""

class ForbiddenError(PermissionError):
    """Знаю кто ты, нельзя. → 403."""

class RateLimitError(Exception):
    """→ 429."""
```
(`AuthError` уже в `app/auth.py` — его тоже маппим.)

- [ ] **Step 2: `app/error_handlers.py`**
```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth import AuthError
from app.exceptions import (BadInputError, ConflictError, ForbiddenError,
                            NotFoundError, RateLimitError)

_MAP = [(BadInputError, 400), (NotFoundError, 404), (ConflictError, 409),
        (ForbiddenError, 403), (AuthError, 401), (RateLimitError, 429)]


def register_error_handlers(app: FastAPI) -> None:
    for exc_type, status in _MAP:
        def make(status_code):
            def handler(_request: Request, exc: Exception) -> JSONResponse:
                return JSONResponse(status_code=status_code, content={"detail": str(exc)})
            return handler
        app.add_exception_handler(exc_type, make(status))

    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        import logging
        logging.getLogger("renju").exception("Unhandled: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.add_exception_handler(Exception, _unhandled)  # 500 без утечки причины (спека §Обработка ошибок)
```

- [ ] **Step 3: Тест маппинга** `tests/api/test_error_handlers.py`
```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import AuthError
from app.error_handlers import register_error_handlers
from app.exceptions import BadInputError, ConflictError, ForbiddenError, NotFoundError, RateLimitError

@pytest.mark.parametrize("exc,code", [(BadInputError, 400), (NotFoundError, 404),
    (ConflictError, 409), (ForbiddenError, 403), (AuthError, 401), (RateLimitError, 429)])
async def test_exception_maps_to_status(exc, code):
    app = FastAPI()
    register_error_handlers(app)
    @app.get("/boom")
    async def boom():
        raise exc("x")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == code and r.json() == {"detail": "x"}

async def test_unhandled_is_500_no_leak():
    app = FastAPI()
    register_error_handlers(app)
    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret-internal-detail")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                           raise_app_exceptions=False) as c:
        r = await c.get("/boom")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}
```
> Примечание: доменные исключения (`BadInputError(ValueError)` и т.п.) маппятся на свои статусы; любой прочий (`RuntimeError`) ловит generic-handler → 500 `{"detail": "Internal server error"}` (причина в лог, не в ответ).

- [ ] **Step 4: Прогнать — PASS.** Run: `uv run pytest tests/api/test_error_handlers.py -v`.

- [ ] **Step 5: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/exceptions.py app/error_handlers.py tests/api
git commit -m "feat(rj-a4k): доменные исключения + маппинг класс→HTTP-статус"
```

---

## Task 7: DTO + auth_service (login + rate-limit + get_me)

**Files:**
- Create: `app/dtos/__init__.py`, `app/dtos/auth.py`, `app/services/__init__.py`, `app/services/auth_service.py`
- Test: `tests/unit/test_auth_service.py`

- [ ] **Step 1: `app/dtos/auth.py`**
```python
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str = Field(min_length=1, max_length=72)  # bcrypt усекает >72 байт


class UserDTO(BaseModel):
    id: int
    username: str
    role: str


class LoginResponse(BaseModel):
    ok: bool = True
    user: UserDTO
```

- [ ] **Step 2: Тесты (red)** `tests/unit/test_auth_service.py`
```python
import pytest
from app.auth import AuthError, decode_token
from app.config import Settings
from app.dal import users as dal
from app.exceptions import RateLimitError
from app.services import auth_service

# env с tmp data_dir активен в теле теста через фикстуру session (engine → monkeypatch)

async def test_login_ok(session):
    await dal.create_user(session, "alice", "pw", role="admin")
    await session.commit()
    auth_service.reset_rate_limit()
    cfg = Settings()
    token, user = await auth_service.login(session, "alice", "pw", ip="1.1.1.1", settings=cfg)
    assert user.username == "alice" and user.role == "admin"
    assert decode_token(token, cfg)["userId"] == user.id

async def test_login_bad_password(session):
    await dal.create_user(session, "alice", "pw")
    await session.commit()
    auth_service.reset_rate_limit()
    with pytest.raises(AuthError):
        await auth_service.login(session, "alice", "WRONG", ip="2.2.2.2", settings=Settings())

async def test_rate_limit_after_5(session):
    auth_service.reset_rate_limit()
    for _ in range(5):
        with pytest.raises(AuthError):
            await auth_service.login(session, "ghost", "x", ip="3.3.3.3", settings=Settings())
    with pytest.raises(RateLimitError):
        await auth_service.login(session, "ghost", "x", ip="3.3.3.3", settings=Settings())
```

- [ ] **Step 3: Прогнать — FAIL.** Run: `uv run pytest tests/unit/test_auth_service.py -v`.

- [ ] **Step 4: `app/services/auth_service.py`**
```python
import time

from app.auth import AuthError, create_token, verify_password
from app.dal import users as dal
from app.dtos.auth import UserDTO
from app.exceptions import RateLimitError

_MAX_ATTEMPTS = 5
_WINDOW_SEC = 300
_MAX_TRACKED_IPS = 10_000
_attempts: dict[str, list[float]] = {}  # секции синхронны (без await) → атомарны в loop


def reset_rate_limit() -> None:
    _attempts.clear()


def _purge(now: float) -> None:
    for ip in [ip for ip, ts in _attempts.items() if all(now - t >= _WINDOW_SEC for t in ts)]:
        del _attempts[ip]


def _allowed(ip: str, now: float) -> bool:
    if len(_attempts) > _MAX_TRACKED_IPS:
        _purge(now)
    fresh = [t for t in _attempts.get(ip, []) if now - t < _WINDOW_SEC]
    if fresh:
        _attempts[ip] = fresh
    else:
        _attempts.pop(ip, None)
    return len(fresh) < _MAX_ATTEMPTS


async def login(session, username: str, password: str, ip: str, settings) -> tuple[str, UserDTO]:
    now = time.monotonic()
    if not _allowed(ip, now):
        raise RateLimitError("Too many login attempts")
    user = await dal.get_user_by_username(session, username)
    if user is None or not verify_password(password, user.password_hash):
        _attempts.setdefault(ip, []).append(now)
        raise AuthError("Invalid credentials")
    _attempts.pop(ip, None)
    token = create_token(user.id, user.role, user.token_epoch, settings)
    return token, UserDTO(id=user.id, username=user.username, role=user.role)


async def get_me(session, user_id: int) -> UserDTO:
    from app.exceptions import NotFoundError
    user = await dal.get_user_by_id(session, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return UserDTO(id=user.id, username=user.username, role=user.role)
```

- [ ] **Step 5: Прогнать — PASS.** Run: `uv run pytest tests/unit/test_auth_service.py -v`.

- [ ] **Step 6: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/dtos app/services/__init__.py app/services/auth_service.py tests/unit/test_auth_service.py
git commit -m "feat(rj-a4k): auth_service — login + rate-limit (+purge-кэп) + get_me"
```

---

## Task 8: get_current_user + require_admin (зависимости)

**Files:**
- Modify: `app/auth.py` (добавить `get_current_user`, `require_admin`, `token_needs_refresh`)
- Test: `tests/api/test_current_user.py` (через мини-app в Task 9; здесь — юнит на `token_needs_refresh`)

- [ ] **Step 1: Юнит на refresh (red)** в `tests/unit/test_auth_primitives.py` добавить:
```python
def test_token_needs_refresh_unix_iat(cfg):
    from app.auth import token_needs_refresh
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(hours=200)).timestamp()  # unix-timestamp!
    assert token_needs_refresh({"iat": old}, cfg) is True
    fresh = datetime.now(timezone.utc).timestamp()
    assert token_needs_refresh({"iat": fresh}, cfg) is False
```

- [ ] **Step 2: Добавить в `app/auth.py`**

`get_current_user` берёт `Request` + `AsyncSession`. Сессия инжектится зависимостью `get_session` (определяется в Task 9 app_factory); сигнатуру оставляем на `AsyncSession`, связывание — в роутерах.
```python
from datetime import datetime, timezone, timedelta

from fastapi import Request

from app.exceptions import ForbiddenError


def token_needs_refresh(payload: dict, settings: Settings) -> bool:
    iat = payload.get("iat")
    if not iat:
        return False
    # iat кладётся как datetime, PyJWT декодирует как unix-timestamp
    issued = datetime.fromtimestamp(iat, tz=timezone.utc)
    return datetime.now(timezone.utc) - issued > timedelta(hours=settings.jwt_refresh_after_hours)


async def get_current_user(request: Request, session, settings: Settings) -> CurrentUser:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise AuthError("Not authenticated")
    try:
        payload = decode_token(token, settings)
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired")
    except jwt.InvalidTokenError:
        raise AuthError(_INVALID)
    user = CurrentUser.from_payload(payload)
    # token_epoch — прямо из БД (без кеша); §4.4
    db_epoch = await fetch_token_epoch(session, user.user_id)
    if db_epoch is None or payload.get("tep", 0) != db_epoch:
        raise AuthError(_INVALID)
    if token_needs_refresh(payload, settings):
        request.state.refresh = {"user_id": user.user_id, "role": user.role, "epoch": db_epoch}
    return user


def require_admin(user: CurrentUser) -> CurrentUser:
    if user.role != "admin":
        raise ForbiddenError("Admin access required")
    return user
```
> `get_current_user(request, session)` и `require_admin(user)` обёртываются в FastAPI-`Depends` в роутерах (Task 9/10) — там session приходит из `get_session`, а `require_admin` — из `Depends(get_current_user)`.

- [ ] **Step 3: Прогнать юнит refresh — PASS.** Run: `uv run pytest tests/unit/test_auth_primitives.py::test_token_needs_refresh_unix_iat -v`. (Полный e2e get_current_user — в Task 9 через /me.)

- [ ] **Step 4: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/auth.py tests/unit/test_auth_primitives.py
git commit -m "feat(rj-a4k): get_current_user (epoch из БД, без кеша) + require_admin + refresh"
```

---

## Task 9: app_factory + middlewares + auth-роутер

**Files:**
- Create: `app/middleware/__init__.py`, `app/middleware/security_headers.py`, `app/middleware/csrf.py`, `app/middleware/refresh.py`, `app/routers/__init__.py`, `app/routers/auth.py`, `app/app_factory.py`
- Modify: `tests/conftest.py` (фикстура `client`)
- Test: `tests/api/test_auth_endpoints.py`, `tests/api/test_middleware.py`

- [ ] **Step 1: Middlewares**

`app/middleware/security_headers.py`:
```python
_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; object-src 'none'; "
                                "base-uri 'none'; frame-ancestors 'none'; connect-src 'self'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def add_security_headers(app):
    @app.middleware("http")
    async def _mw(request, call_next):
        resp = await call_next(request)
        for k, v in _HEADERS.items():
            resp.headers.setdefault(k, v)
        if request.app.state.settings.secure_cookie:  # HSTS только на проде (Secure)
            resp.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        return resp
```

`app/middleware/csrf.py`:
```python
from fastapi.responses import JSONResponse

_SAFE = {"GET", "HEAD", "OPTIONS"}


def add_csrf_guard(app):
    @app.middleware("http")
    async def _mw(request, call_next):
        if request.url.path.startswith("/api/") and request.method not in _SAFE:
            if request.headers.get("X-Requested-With") != "XMLHttpRequest":
                return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
        return await call_next(request)
```

`app/middleware/refresh.py`:
```python
from app.auth import create_token


def add_refresh(app):
    @app.middleware("http")
    async def _mw(request, call_next):
        resp = await call_next(request)
        s = request.app.state.settings
        r = getattr(request.state, "refresh", None)
        if r and {"user_id", "role", "epoch"} <= r.keys() and 200 <= resp.status_code < 400:
            token = create_token(r["user_id"], r["role"], r["epoch"], s)
            resp.set_cookie(s.cookie_name, token, httponly=True, samesite="lax",
                            secure=s.secure_cookie, max_age=s.jwt_expire_hours * 3600, path="/")
        return resp
```

- [ ] **Step 2: `app/routers/auth.py`**
```python
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user
from app.config import Settings
from app.db.deps import get_session, get_settings
from app.dtos.auth import LoginRequest, LoginResponse, UserDTO
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return (request.headers.get("X-Real-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


def _set_cookie(response: Response, token: str, s: Settings) -> None:
    response.set_cookie(s.cookie_name, token, httponly=True, samesite="lax",
                        secure=s.secure_cookie, max_age=s.jwt_expire_hours * 3600, path="/")


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, response: Response,
                session: Annotated[AsyncSession, Depends(get_session)],
                settings: Annotated[Settings, Depends(get_settings)]):
    token, user = await auth_service.login(session, body.username, body.password,
                                           _client_ip(request), settings)
    _set_cookie(response, token, settings)
    return LoginResponse(user=user)


async def current_user(request: Request,
                       session: Annotated[AsyncSession, Depends(get_session)],
                       settings: Annotated[Settings, Depends(get_settings)]) -> CurrentUser:
    return await get_current_user(request, session, settings)


@router.get("/me", response_model=UserDTO)
async def me(user: Annotated[CurrentUser, Depends(current_user)],
             session: Annotated[AsyncSession, Depends(get_session)]):
    return await auth_service.get_me(session, user.user_id)


@router.post("/logout")
async def logout(response: Response, settings: Annotated[Settings, Depends(get_settings)]):
    response.delete_cookie(settings.cookie_name, path="/", samesite="lax",
                           secure=settings.secure_cookie)  # epoch не трогаем
    return {"ok": True}
```
> `current_user` здесь — переиспользуемая зависимость (используется и admin-роутером). Вынести в `app/routers/deps.py`, если удобно; пока локально.

- [ ] **Step 3: `app/db/deps.py` (создать) — связать сессию с app-state**
```python
from app.config import Settings
from app.db.session import session_scope


async def get_session(request):
    sm = request.app.state.sessionmaker
    async for s in session_scope(sm):
        yield s


def get_settings(request) -> Settings:
    return request.app.state.settings
```

- [ ] **Step 4: `app/app_factory.py`**
```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db.engine import make_engine
from app.db.session import make_sessionmaker
from app.error_handlers import register_error_handlers
from app.middleware.csrf import add_csrf_guard
from app.middleware.refresh import add_refresh
from app.middleware.security_headers import add_security_headers
from app.routers import auth as auth_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        yield
        await engine.dispose()

    app = FastAPI(title="Renju", lifespan=lifespan)
    app.state.settings = settings  # доступно мидлварам/зависимостям на request-time
    register_error_handlers(app)
    add_security_headers(app)   # порядок: добавляются как слои; security — внешний
    add_csrf_guard(app)
    add_refresh(app)
    app.include_router(auth_router.router)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app
```

- [ ] **Step 5: Фикстура `client` в `tests/conftest.py`**
```python
@pytest_asyncio.fixture
async def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    from app.app_factory import create_app
    from app.config import Settings
    from app.db.base import Base
    import app.models.user  # noqa: F401
    application = create_app(Settings())
    async with application.router.lifespan_context(application):  # поднимает engine/sessionmaker
        async with application.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield application

@pytest_asyncio.fixture
async def client(app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                           headers={"X-Requested-With": "XMLHttpRequest"}) as c:
        yield c
```
> Тесты, которым нужен доступ к `app.state.sessionmaker` (засев данных), берут фикстуру `app` рядом с `client` — без хрупкого `client._transport.app`.

- [ ] **Step 6: Тест эндпоинтов** `tests/api/test_auth_endpoints.py`
```python
from app.auth import bump_token_epoch

async def _seed_admin(app):
    from app.dal import users as dal
    async with app.state.sessionmaker() as s:
        await dal.create_user(s, "admin", "pw", role="admin")
        await s.commit()

async def test_health(client):
    assert (await client.get("/api/health")).json() == {"ok": True}

async def test_login_me_logout(app, client):
    await _seed_admin(app)
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert client.cookies.get("renju_token")
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "admin"
    await client.post("/api/auth/logout")
    client.cookies.clear()  # cookie снят → /me даёт 401
    assert (await client.get("/api/auth/me")).status_code == 401

async def test_me_requires_cookie(client):
    assert (await client.get("/api/auth/me")).status_code == 401

async def test_epoch_revocation(app, client):
    await _seed_admin(app)
    await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert (await client.get("/api/auth/me")).status_code == 200
    async with app.state.sessionmaker() as s:  # отозвать: bump epoch
        from app.dal import users as dal
        u = await dal.get_user_by_username(s, "admin")
        await bump_token_epoch(s, u.id)
        await s.commit()
    assert (await client.get("/api/auth/me")).status_code == 401  # старый токен мёртв
```

- [ ] **Step 7: Тест middleware** `tests/api/test_middleware.py`
```python
async def test_security_headers(client):
    r = await client.get("/api/health")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"

async def test_csrf_blocks_post_without_header(client):
    r = await client.post("/api/auth/login", json={"username": "x", "password": "y"},
                          headers={"X-Requested-With": ""})
    assert r.status_code == 403
```

- [ ] **Step 8: Прогнать — PASS.** Run: `uv run pytest tests/api -v`. Чинить связывание зависимостей до зелёного.

- [ ] **Step 9: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/middleware app/routers app/app_factory.py app/db/deps.py tests
git commit -m "feat(rj-a4k): app-factory + middlewares (headers/CSRF/refresh) + /api/auth/* + /health"
```

---

## Task 10: admin_service + admin-роутер (user CRUD + guards)

**Files:**
- Create: `app/services/admin_service.py`, `app/routers/admin.py`
- Modify: `app/app_factory.py` (подключить admin-роутер)
- Test: `tests/api/test_admin_users.py`

- [ ] **Step 1: Тесты (red)** `tests/api/test_admin_users.py`
```python
async def _login(app, client, username="admin", password="pw"):
    from app.dal import users as dal
    async with app.state.sessionmaker() as s:
        if not await dal.get_user_by_username(s, username):
            await dal.create_user(s, username, password, role="admin")
            await s.commit()
    await client.post("/api/auth/login", json={"username": username, "password": password})

async def test_create_and_list_users(app, client):
    await _login(app, client)
    r = await client.post("/api/admin/users",
                          json={"username": "bob", "password": "pw", "role": "user"})
    assert r.status_code == 200
    users = (await client.get("/api/admin/users")).json()
    assert {u["username"] for u in users} >= {"admin", "bob"}

async def test_non_admin_forbidden(app, client):
    await _login(app, client)
    await client.post("/api/admin/users", json={"username": "bob", "password": "pw", "role": "user"})
    client.cookies.clear()
    await client.post("/api/auth/login", json={"username": "bob", "password": "pw"})
    assert (await client.post("/api/admin/users",
            json={"username": "x", "password": "pw", "role": "user"})).status_code == 403

async def test_cannot_delete_self(app, client):
    await _login(app, client)
    me = (await client.get("/api/auth/me")).json()
    assert (await client.delete(f"/api/admin/users/{me['id']}")).status_code == 409

async def test_cannot_delete_last_admin(app, client):
    await _login(app, client)
    # admin — единственный; удалить себя ловится self-delete-guard'ом (409) раньше
    # last-admin-guard. Проверяем удаление НЕ-последнего/НЕ-себя через второго админа:
    await client.post("/api/admin/users", json={"username": "a2", "password": "pw", "role": "admin"})
    a2 = next(u for u in (await client.get("/api/admin/users")).json() if u["username"] == "a2")
    assert (await client.delete(f"/api/admin/users/{a2['id']}")).status_code == 200

async def test_delete_nonexistent_404(app, client):
    await _login(app, client)
    assert (await client.delete("/api/admin/users/9999")).status_code == 404

async def test_reset_password_revokes(app, client):
    await _login(app, client)
    await client.post("/api/admin/users", json={"username": "bob", "password": "pw", "role": "user"})
    bob = next(u for u in (await client.get("/api/admin/users")).json() if u["username"] == "bob")
    client.cookies.clear()
    await client.post("/api/auth/login", json={"username": "bob", "password": "pw"})  # bob входит
    assert (await client.get("/api/auth/me")).status_code == 200
    bob_cookie = client.cookies.get("renju_token")
    client.cookies.clear()
    await _login(app, client)  # снова админ
    assert (await client.post(f"/api/admin/users/{bob['id']}/reset-password",
            json={"password": "newpw"})).status_code == 200  # epoch bump
    client.cookies.clear()
    client.cookies.set("renju_token", bob_cookie)
    assert (await client.get("/api/auth/me")).status_code == 401  # старый токен bob мёртв
```

- [ ] **Step 2: `app/services/admin_service.py`**
```python
from app.auth import bump_token_epoch
from app.dal import users as dal
from app.dtos.auth import UserDTO
from app.exceptions import ConflictError, NotFoundError


async def list_users(session) -> list[UserDTO]:
    return [UserDTO(id=u.id, username=u.username, role=u.role) for u in await dal.list_users(session)]


async def create_user(session, username: str, password: str, role: str) -> int:
    if await dal.get_user_by_username(session, username) is not None:
        raise ConflictError("Username already exists")
    uid = await dal.create_user(session, username, password, role=role)
    await session.commit()  # писатель коммитит ЯВНО (session_scope не коммитит)
    return uid


async def delete_user(session, target_id: int, actor_id: int) -> None:
    target = await dal.get_user_by_id(session, target_id)
    if target is None:
        raise NotFoundError("User not found")
    if target_id == actor_id:
        raise ConflictError("Cannot delete yourself")
    if await dal.is_last_admin(session, target_id):
        raise ConflictError("Cannot delete the last admin")
    await dal.delete_user(session, target_id)
    await session.commit()


async def reset_password(session, target_id: int, new_password: str) -> None:
    from app.auth import hash_password
    target = await dal.get_user_by_id(session, target_id)
    if target is None:
        raise NotFoundError("User not found")
    target.password_hash = hash_password(new_password)
    await bump_token_epoch(session, target_id)  # отзыв сессий (autoflush сбросит password_hash)
    await session.commit()
```

- [ ] **Step 3: `app/routers/admin.py`**
```python
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, require_admin
from app.db.deps import get_session
from app.dtos.auth import UserDTO
from app.routers.auth import current_user
from app.services import admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def admin_user(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    return require_admin(user)


class CreateUserBody(BaseModel):
    username: str
    password: str = Field(min_length=1, max_length=72)
    role: Literal["admin", "user"] = "user"


class ResetPasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=72)


@router.get("/users", response_model=list[UserDTO])
async def list_users(_: Annotated[CurrentUser, Depends(admin_user)],
                     session: Annotated[AsyncSession, Depends(get_session)]):
    return await admin_service.list_users(session)


@router.post("/users")
async def create_user(body: CreateUserBody, _: Annotated[CurrentUser, Depends(admin_user)],
                      session: Annotated[AsyncSession, Depends(get_session)]):
    uid = await admin_service.create_user(session, body.username, body.password, body.role)
    return {"id": uid}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, actor: Annotated[CurrentUser, Depends(admin_user)],
                      session: Annotated[AsyncSession, Depends(get_session)]):
    await admin_service.delete_user(session, user_id, actor.user_id)
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, body: ResetPasswordBody,
                         _: Annotated[CurrentUser, Depends(admin_user)],
                         session: Annotated[AsyncSession, Depends(get_session)]):
    await admin_service.reset_password(session, user_id, body.password)
    return {"ok": True}
```

- [ ] **Step 4: Подключить роутер** в `app/app_factory.py`: импорт `from app.routers import admin as admin_router` и `app.include_router(admin_router.router)` после auth-роутера.

- [ ] **Step 5: Прогнать — PASS.** Run: `uv run pytest tests/api/test_admin_users.py -v`. Затем весь набор `uv run pytest -q`.

- [ ] **Step 6: Линт + коммит**
```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/services/admin_service.py app/routers/admin.py app/app_factory.py tests/api/test_admin_users.py
git commit -m "feat(rj-a4k): admin users CRUD (require_admin, self-delete/last-admin guards, reset→bump epoch)"
```

---

## Task 11: CLI bootstrap первого админа

**Files:**
- Create: `scripts/create_admin.py`
- Test: `tests/api/test_create_admin.py`

- [ ] **Step 1: Тест (red)** `tests/api/test_create_admin.py`
```python
async def test_create_admin_inserts(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    from app.config import Settings
    from app.db.base import Base
    from app.db.engine import make_engine
    import app.models.user  # noqa: F401
    eng = make_engine(Settings())
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()

    from scripts.create_admin import create_admin
    await create_admin("root", "pw")

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from app.dal import users as dal
    eng2 = create_async_engine(f"sqlite+aiosqlite:///{Settings().resolved_db_path}")
    async with AsyncSession(eng2) as s:
        u = await dal.get_user_by_username(s, "root")
        assert u is not None and u.role == "admin"
    await eng2.dispose()
```

- [ ] **Step 2: `scripts/create_admin.py`**
```python
"""CLI: создать первого админа.  uv run python -m scripts.create_admin <username> <password>"""
import asyncio
import sys

from app.config import Settings
from app.dal import users as dal
from app.db.engine import make_engine
from app.db.session import make_sessionmaker


async def create_admin(username: str, password: str) -> None:
    engine = make_engine(Settings())
    sm = make_sessionmaker(engine)
    try:
        async with sm() as session:
            if await dal.get_user_by_username(session, username) is not None:
                print(f"User '{username}' already exists.")
                raise SystemExit(1)
            uid = await dal.create_user(session, username, password, role="admin")
            await session.commit()
            print(f"Admin '{username}' created (id={uid}).")
    finally:
        await engine.dispose()


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.create_admin <username> <password>")
        raise SystemExit(2)
    asyncio.run(create_admin(sys.argv[1], sys.argv[2]))


if __name__ == "__main__":
    main()
```
> Без дефолтов `admin/admin` — требуем явные аргументы. Запуск после `uv run alembic upgrade head`.

- [ ] **Step 3: Прогнать — PASS.** Run: `uv run pytest tests/api/test_create_admin.py -v`.

- [ ] **Step 4: Полный прогон + линт**
```bash
uv run pytest -q
uv run ruff check app tests scripts && uv run ruff format app tests scripts
```
Expected: всё зелёное.

- [ ] **Step 5: Коммит**
```bash
git add scripts/create_admin.py tests/api/test_create_admin.py
git commit -m "feat(rj-a4k): CLI bootstrap первого админа (async, commit+dispose)"
```

---

## Task 12: Ручной smoke (Alexey, шаг 10) — НЕ автоматизировать

- [ ] **Step 1: Поднять БД и админа**
```bash
RENJU_DATA_DIR=./data uv run alembic upgrade head
RENJU_DATA_DIR=./data uv run python -m scripts.create_admin root secretpw
RENJU_DATA_DIR=./data uv run uvicorn app.app_factory:create_app --factory --reload
```

- [ ] **Step 2: Проверить curl'ом** (Alexey):
  - `curl -i -X POST localhost:8000/api/auth/login -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' -d '{"username":"root","password":"secretpw"}' -c cookies.txt` → 200 + `Set-Cookie`.
  - `curl localhost:8000/api/auth/me -b cookies.txt` → `{id, username:"root", role:"admin"}`.
  - POST без `X-Requested-With` → 403 (CSRF).
  - Создать юзера через `/api/admin/users`, войти им, `/api/admin/users` под ним → 403.
  - Проверить заголовки в ответе (`X-Frame-Options`, CSP).

- [ ] **Step 3: После одобрения Alexey — финальный статус.** (Мерж/пуш — отдельной командой.)

---

## Self-Review (проведено)

- **Покрытие спеки:** каркас+lifespan (T9) · БД async+pragmas (T2) · модель User+Alembic+миграция (T3) · auth-примитивы (T4) · token_epoch без кеша/get_current_user (T8) · DAL (T5) · login+rate-limit+purge (T7) · /api/auth/* (T9) · admin CRUD+guards (T10) · middlewares headers/CSRF/refresh (T9) · ошибки→статус (T6) · bootstrap (T11) · smoke (T12). Все разделы спеки имеют задачу.
- **Перенос-граблей зафиксирован:** `iat` unix-timestamp (T8), bump RETURNING→None (T5), self-delete+last-admin→409 (T10), 404 на несуществующий id (T10), purge-кэп (T7), PRAGMA на `sync_engine` (T2), **`session_scope` без авто-commit — писатели коммитят явно** (T2/T10), **`settings` параметром, не модуль-левел `Settings()`** (T4/T8/T9), generic-`Exception`→500 без утечки (T6), HSTS на проде (T9), data_dir-override в тестах (фикстуры), create_admin commit+dispose (T11), refresh все поля (T9).
- **Типы согласованы:** `CurrentUser`, `UserDTO`, `get_session`, `current_user`, `bump_token_epoch`/`fetch_token_epoch` — имена сквозные между задачами.
- **Без плейсхолдеров:** код в каждом шаге полный.

## Что НЕ в этом плане (scope — не предлагать как findings)

- Игровой контур (фасад `Player`, `advance`, очередь хода, движок в lifespan, SSE/EventHub) — срез 2.
- `user_settings` (undo-политика), PUT-смена-роли, полный профиль-CRUD — позже/аддитивно.
- Frontend/PWA, страница логина — этап 4.
- Мультиворкер, бэкапы, Postgres, OAuth/2FA — вне MVP.
