"""Тест DAL конфигурации: ConfigRepository."""

import pytest

from app.config_repository import ConfigRepository


@pytest.mark.asyncio
async def test_config_repository_levels_ordered(session):
    from tests.conftest import _seed_levels

    await _seed_levels(session)

    repo = ConfigRepository(session)
    levels = await repo.levels()

    # Проверяем порядок по ordering
    orderings = [lv.ordering for lv in levels]
    assert orderings == sorted(orderings)
    assert levels[0].ordering == 0  # novice первый
    assert levels[-1].ordering == 6  # god последний


@pytest.mark.asyncio
async def test_config_repository_get_level_master(session):
    from tests.conftest import _seed_levels

    await _seed_levels(session)

    repo = ConfigRepository(session)
    level = await repo.get_level("master")

    assert level is not None
    assert level.strength == 90


@pytest.mark.asyncio
async def test_config_repository_nnue_true(session):
    from tests.conftest import _seed_levels

    await _seed_levels(session)

    repo = ConfigRepository(session)
    assert await repo.nnue() is True


@pytest.mark.asyncio
async def test_config_repository_get_level_missing(session):
    from tests.conftest import _seed_levels

    await _seed_levels(session)

    repo = ConfigRepository(session)
    assert await repo.get_level("nonexistent") is None
