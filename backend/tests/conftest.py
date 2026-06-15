from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import REPO_ROOT, Settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def rapfi_paths(settings):
    """(bin, config, cwd) реального движка; скип, если бинарь не собран."""
    try:
        bin_path = settings.resolved_rapfi_bin()
    except FileNotFoundError:
        pytest.skip("Rapfi binary not built — run engine/build.sh")
    if not settings.rapfi_config.exists():
        pytest.skip("engine/config.toml missing")
    return bin_path, settings.rapfi_config, REPO_ROOT


@pytest_asyncio.fixture
async def engine(tmp_path, monkeypatch) -> AsyncIterator[AsyncEngine]:
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    import app.models.game  # noqa: F401
    import app.models.user  # noqa: F401 — регистрирует таблицу в metadata
    import app.models.user_settings  # noqa: F401
    from app.config import Settings
    from app.db.base import Base
    from app.db.engine import make_engine

    eng = make_engine(Settings())
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    from app.db.session import make_sessionmaker

    sm = make_sessionmaker(engine)
    async with sm() as s:
        yield s


@pytest_asyncio.fixture
async def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    import app.models.game  # noqa: F401
    import app.models.user  # noqa: F401
    import app.models.user_settings  # noqa: F401
    from app.app_factory import create_app
    from app.config import Settings
    from app.db.base import Base

    application = create_app(Settings())
    async with application.router.lifespan_context(application):  # поднимает engine/sessionmaker
        async with application.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield application


@pytest_asyncio.fixture
async def client(app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ) as c:
        yield c


class _FakeAdapter:
    """Фейк-движок для юнит-API: ходит в ПЕРВУЮ свободную клетку зоны (без коллизий в advance)."""

    async def forbidden_points(self, game_id, moves, *, level_tag="-"):
        return []

    async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
        occupied = {tuple(m) for m in moves}
        cells = (
            sorted(allowed_zone) if allowed_zone else [(x, y) for x in range(15) for y in range(15)]
        )
        for c in cells:
            if tuple(c) not in occupied:
                return tuple(c)
        raise AssertionError("board full")

    async def sync_after_undo(self, game_id, moves, *, level_tag="-"):
        pass

    async def mark_present(self, game_id, level_tag="-"):
        pass

    async def mark_absent(self, game_id, *, reason="leave"):
        pass

    async def sweep_once(self):
        pass

    async def release(self, game_id, *, reason="delete"):
        pass

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

    return SimpleNamespace(
        FakeAdapter=_FakeAdapter,
        seed_login=seed_login,
        wait_settled=wait_settled,
        free_move=free_move,
    )
