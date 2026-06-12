import asyncio

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
            got.append(ev)
            if ev["payload"].get("n") == 3:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    hub.publish("g1", "move", {"n": 3})  # live
    await asyncio.wait_for(task, 1)
    # реплей с курсора 1 даёт seq>1 (n=2) + live (n=3)
    assert [e["payload"]["n"] for e in got] == [2, 3]


async def test_reset_when_cursor_in_future():
    hub = InMemoryEventHub()
    hub.publish("g1", "move", {"n": 1})
    first: dict | None = None
    async for ev in hub.subscribe("g1", since=999):
        first = ev
        break
    assert first is not None
    assert first["type"] == "reset"


async def test_subscribe_heartbeat_ping_on_idle():
    hub = InMemoryEventHub()
    gen = hub.subscribe("g1", since=0, idle_timeout=0.02)
    ev = await asyncio.wait_for(gen.__anext__(), 1)  # нет событий → ping, подписка ЖИВА
    assert ev["type"] == "ping"
    # второй idle → снова ping (не StopAsyncIteration)
    nxt = await asyncio.wait_for(gen.__anext__(), 1)
    assert nxt["type"] == "ping"
    await gen.aclose()
