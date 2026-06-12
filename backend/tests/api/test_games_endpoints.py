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
