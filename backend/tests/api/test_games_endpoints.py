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
    assert (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).status_code == 401


async def test_levels_endpoint(app, client, games_api):
    await games_api.seed_login(app, client)
    r = await client.get("/api/levels")
    assert r.status_code == 200 and any(lv["id"] == "master" for lv in r.json())


async def test_create_unknown_level_400(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    r = await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "nope"}})
    assert r.status_code == 400  # BadInputError→400 (единая модель ошибок среза 1)


async def test_move_then_undo(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
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
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)
    r = await client.post(f"/api/games/{gid}/move", json={"x": 7, "y": 7})  # центр занят → OCCUPIED
    assert r.status_code == 422


async def test_move_when_opponent_thinking_409(app, client, games_api):
    from app.models.game import Game

    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)
    # детерминированно загнать в opponent_thinking; без GET — фон не планируем
    async with app.state.sessionmaker() as s:
        g = await s.get(Game, gid)
        g.status = "opponent_thinking"
        await s.commit()
    r = await client.post(f"/api/games/{gid}/move", json={"x": 6, "y": 6})
    assert r.status_code == 409  # MoveRejected(OPPONENT_THINKING) → 409


async def test_enter_leave_call_registry(app, client, games_api):
    calls = []

    class PresenceAdapter(games_api.FakeAdapter):
        async def mark_present(self, game_id, level_tag="-"):
            calls.append(("enter", game_id))

        async def mark_absent(self, game_id, *, reason="leave"):
            calls.append(("leave", game_id))

    app.state.adapter = PresenceAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    assert (await client.post(f"/api/games/{gid}/enter")).status_code == 200
    assert (await client.post(f"/api/games/{gid}/leave")).status_code == 200
    assert ("enter", gid) in calls and ("leave", gid) in calls


async def test_move_rejection_is_logged(app, client, games_api, caplog):
    import logging

    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)
    with caplog.at_level(logging.WARNING, logger="renju.games"):
        # центр занят → OCCUPIED
        r = await client.post(f"/api/games/{gid}/move", json={"x": 7, "y": 7})
    assert r.status_code == 422
    msgs = " ".join(rec.getMessage() for rec in caplog.records)
    assert "move rejected" in msgs and "occupied" in msgs and gid in msgs
