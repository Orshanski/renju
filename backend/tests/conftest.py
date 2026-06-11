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
    import app.models.user  # noqa: F401 — регистрирует таблицу в metadata

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
