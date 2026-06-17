# backend/tests/api/test_settings_router.py


async def _login(app, client, username="alice", password="pw"):
    from app.dal import users as dal

    async with app.state.sessionmaker() as s:
        if not await dal.get_user_by_username(s, username):
            await dal.create_user(s, username, password)
            await s.commit()
    await client.post("/api/auth/login", json={"username": username, "password": password})


async def test_get_settings_returns_defaults(app, client):
    await _login(app, client)
    r = await client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["games_limit"] == 50
    assert body["games_limit_enabled"] is True
    assert body["undo_enabled"] is True
    assert body["undo_limit"] is None
    assert body["undo_after_game_end"] is True


async def test_get_settings_requires_auth(app, client):
    r = await client.get("/api/settings")
    assert r.status_code == 401


async def test_put_settings_saves_and_returns(app, client):
    await _login(app, client)
    body = {
        "games_limit": 30,
        "games_limit_enabled": True,
        "undo_enabled": False,
        "undo_limit": None,
        "undo_after_game_end": False,
    }
    r = await client.put("/api/settings", json=body)
    assert r.status_code == 200
    resp = r.json()
    assert resp["games_limit"] == 30
    assert resp["undo_enabled"] is False
    assert resp["undo_after_game_end"] is False


async def test_put_settings_validates_limit_range(app, client):
    await _login(app, client)
    r = await client.put("/api/settings", json={
        "games_limit": 5,  # < 10 → 422
        "games_limit_enabled": True,
        "undo_enabled": True,
        "undo_limit": None,
        "undo_after_game_end": True,
    })
    assert r.status_code == 422


async def test_change_password_wrong_current(app, client):
    await _login(app, client)
    r = await client.put("/api/settings/password", json={
        "current_password": "wrong",
        "new_password": "newpass123",
    })
    assert r.status_code == 400


async def test_change_password_success_keeps_session(app, client):
    await _login(app, client)
    r = await client.put("/api/settings/password", json={
        "current_password": "pw",
        "new_password": "newpass123",
    })
    assert r.status_code == 204
    # Текущая сессия должна работать (cookie обновлён)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200


async def test_change_password_new_epoch_in_cookie(app, client):
    """После смены пароля cookie содержит новый token_epoch."""
    from app.auth import decode_token
    from app.config import Settings

    await _login(app, client)
    # Запомнить текущий epoch
    old_cookie = client.cookies.get("renju_token")
    old_epoch = decode_token(old_cookie, Settings()).get("tep", 0)

    r = await client.put("/api/settings/password", json={
        "current_password": "pw",
        "new_password": "newpass123",
    })
    assert r.status_code == 204

    new_cookie = client.cookies.get("renju_token")
    new_epoch = decode_token(new_cookie, Settings()).get("tep", 0)
    assert new_epoch == old_epoch + 1


async def test_bulk_delete_current(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()  # избежать реального движка
    await games_api.seed_login(app, client)
    # Создать две партии
    r1 = await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    assert r1.status_code == 200
    r2 = await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    assert r2.status_code == 200

    r = await client.delete("/api/games?section=current")
    assert r.status_code == 204

    # Список должен быть пустым
    games = await client.get("/api/games/summary?section=current")
    assert games.json() == []


async def test_bulk_delete_favorite_returns_422(app, client):
    await _login(app, client)
    r = await client.delete("/api/games?section=favorite")
    assert r.status_code == 422
