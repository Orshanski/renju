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
