def _force_black(monkeypatch):
    # патчится атрибут САМОГО модуля random (games.py делает import random) — глобально
    # на время теста; pytest последователен и monkeypatch откатит — безопасно (ревью плана, M2)
    import app.routers.games as games_router

    monkeypatch.setattr(games_router.random, "choice", lambda seq: "black")


async def _play_black_five(client, games_api, gid):
    """Человек-чёрный строит горизонталь y=7 (центр (7,7) предзаполнен).
    (8,7) попадает в дебютную зону 5×5 хода №2; FakeAdapter-белый ходит
    (6,6) (первая клетка зоны 3×3), дальше (0,0),(0,1),(0,2) — не мешает."""
    for x in (8, 9, 10, 11):
        st = await games_api.wait_settled(client, gid)
        assert st["status"] == "awaiting_move"
        r = await client.post(f"/api/games/{gid}/move", json={"x": x, "y": 7})
        assert r.status_code == 202


async def test_state_and_status_event_carry_winning_line(app, client, games_api, monkeypatch):
    _force_black(monkeypatch)
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    ).json()["id"]
    await _play_black_five(client, games_api, gid)

    st = await games_api.wait_settled(client, gid)
    assert st["status"] == "finished_black"
    assert sorted(map(tuple, st["winning_line"])) == [(7, 7), (8, 7), (9, 7), (10, 7), (11, 7)]

    # финальное status-событие несёт ту же линию (контракт SSE; буфер хаба детерминирован)
    status_events = [e for e in app.state.event_hub._log[gid] if e["type"] == "status"]
    assert status_events[-1]["payload"]["status"] == "finished_black"
    assert status_events[-1]["payload"]["winning_line"] == st["winning_line"]
    # нефинальные status поле не несут
    assert all("winning_line" not in e["payload"] for e in status_events[:-1])


async def test_winning_line_null_while_game_running_and_after_undo(
    app, client, games_api, monkeypatch
):
    _force_black(monkeypatch)
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    ).json()["id"]
    st = await games_api.wait_settled(client, gid)
    assert st["winning_line"] is None  # партия идёт

    await _play_black_five(client, games_api, gid)
    st = await games_api.wait_settled(client, gid)
    assert st["status"] == "finished_black" and st["winning_line"] is not None

    un = (
        await client.post(f"/api/games/{gid}/undo")
    ).json()  # дефолтная политика: после конца можно  # noqa: E501
    assert un["status"] == "awaiting_move" and un["winning_line"] is None
