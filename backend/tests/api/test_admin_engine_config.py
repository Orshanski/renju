async def _login_admin(app, client, username="admin", password="pw"):
    from app.dal import users as dal

    async with app.state.sessionmaker() as s:
        if not await dal.get_user_by_username(s, username):
            await dal.create_user(s, username, password, role="admin")
            await s.commit()
    await client.post("/api/auth/login", json={"username": username, "password": password})


async def test_get_engine_config_returns_max_depth_and_ceiling(app, client):
    """GET отдаёт max_depth и depth_ceiling для каждого уровня."""
    await _login_admin(app, client)
    levels = (await client.get("/api/admin/engine-config")).json()["levels"]
    novice = next(lv for lv in levels if lv["id"] == "novice")
    assert novice["max_depth"] == 4  # сид = depth_ceiling(5)
    assert novice["depth_ceiling"] == 4
    god = next(lv for lv in levels if lv["id"] == "god")
    assert god["depth_ceiling"] == 16  # depth_ceiling(100)


async def test_get_engine_config_admin(app, client):
    """GET /api/admin/engine-config — 200, отдаёт levels + nnue."""
    await _login_admin(app, client)
    r = await client.get("/api/admin/engine-config")
    assert r.status_code == 200
    data = r.json()
    assert "levels" in data
    assert "nnue" in data
    assert data["nnue"] is True
    levels = data["levels"]
    assert len(levels) == 7
    # порядок по ordering
    ids = [lv["id"] for lv in levels]
    assert ids == ["novice", "easy", "low_medium", "high_medium", "hard", "master", "god"]
    # каждый уровень имеет нужные поля
    for lv in levels:
        assert set(lv.keys()) >= {"id", "name", "strength", "timeout_ms"}


async def test_put_engine_config_updates(app, client):
    """PUT обновляет strength/timeout_ms/nnue, повторный GET отражает изменения."""
    await _login_admin(app, client)
    r = await client.put(
        "/api/admin/engine-config",
        json={
            "levels": [
                {"id": "novice", "strength": 3, "timeout_ms": 800, "max_depth": 4},
                {"id": "god", "strength": 99, "timeout_ms": 6500, "max_depth": 16},
            ],
            "nnue": False,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["nnue"] is False
    novice = next(lv for lv in data["levels"] if lv["id"] == "novice")
    god = next(lv for lv in data["levels"] if lv["id"] == "god")
    assert novice["strength"] == 3
    assert novice["timeout_ms"] == 800
    assert god["strength"] == 99
    assert god["timeout_ms"] == 6500

    # повторный GET
    r2 = await client.get("/api/admin/engine-config")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["nnue"] is False
    novice2 = next(lv for lv in d2["levels"] if lv["id"] == "novice")
    assert novice2["strength"] == 3
    assert novice2["timeout_ms"] == 800


async def test_put_empty_levels_changes_only_nnue(app, client):
    """PUT с levels:[] меняет только глобальный nnue (уровни не трогает), GET отражает."""
    await _login_admin(app, client)
    r = await client.put("/api/admin/engine-config", json={"levels": [], "nnue": False})
    assert r.status_code == 200
    assert r.json()["nnue"] is False
    d = (await client.get("/api/admin/engine-config")).json()
    assert d["nnue"] is False  # nnue сохранён
    assert len(d["levels"]) == 7  # уровни на месте, не тронуты


async def test_get_engine_config_non_admin_403(app, client):
    """GET даёт 403 для обычного пользователя."""
    await _login_admin(app, client)
    await client.post(
        "/api/admin/users", json={"username": "bob", "password": "pw", "role": "user"}
    )
    client.cookies.clear()
    await client.post("/api/auth/login", json={"username": "bob", "password": "pw"})
    r = await client.get("/api/admin/engine-config")
    assert r.status_code == 403


async def test_put_engine_config_non_admin_403(app, client):
    """PUT даёт 403 для обычного пользователя."""
    await _login_admin(app, client)
    await client.post(
        "/api/admin/users", json={"username": "bob", "password": "pw", "role": "user"}
    )
    client.cookies.clear()
    await client.post("/api/auth/login", json={"username": "bob", "password": "pw"})
    r = await client.put(
        "/api/admin/engine-config",
        json={"levels": [], "nnue": True},
    )
    assert r.status_code == 403


async def test_put_invalid_strength_422(app, client):
    """strength > 100 → 422."""
    await _login_admin(app, client)
    r = await client.put(
        "/api/admin/engine-config",
        json={
            "levels": [{"id": "novice", "strength": 101, "timeout_ms": 1000, "max_depth": 4}],
            "nnue": True,
        },
    )
    assert r.status_code == 422


async def test_put_invalid_strength_negative_422(app, client):
    """strength < 0 → 422."""
    await _login_admin(app, client)
    r = await client.put(
        "/api/admin/engine-config",
        json={
            "levels": [{"id": "novice", "strength": -1, "timeout_ms": 1000, "max_depth": 4}],
            "nnue": True,
        },
    )
    assert r.status_code == 422


async def test_put_invalid_timeout_too_low_422(app, client):
    """timeout_ms < 200 → 422."""
    await _login_admin(app, client)
    r = await client.put(
        "/api/admin/engine-config",
        json={
            "levels": [{"id": "novice", "strength": 5, "timeout_ms": 199, "max_depth": 4}],
            "nnue": True,
        },
    )
    assert r.status_code == 422


async def test_put_invalid_timeout_too_high_422(app, client):
    """timeout_ms > 30000 → 422."""
    await _login_admin(app, client)
    r = await client.put(
        "/api/admin/engine-config",
        json={
            "levels": [{"id": "novice", "strength": 5, "timeout_ms": 30001, "max_depth": 4}],
            "nnue": True,
        },
    )
    assert r.status_code == 422


async def test_put_unknown_level_id_422(app, client):
    """Неизвестный level_id → 422."""
    await _login_admin(app, client)
    r = await client.put(
        "/api/admin/engine-config",
        json={
            "levels": [{"id": "nonexistent_level", "strength": 10, "timeout_ms": 1000}],
            "nnue": True,
        },
    )
    assert r.status_code == 422


async def test_put_atomicity_unknown_id_rolls_back_valid(app, client):
    """PUT с одним валидным + одним неизвестным id — весь запрос отклонён (422),
    валидный уровень тоже НЕ применился."""
    await _login_admin(app, client)
    # запомнить исходные значения novice
    original = (await client.get("/api/admin/engine-config")).json()
    orig_novice = next(lv for lv in original["levels"] if lv["id"] == "novice")
    orig_strength = orig_novice["strength"]

    r = await client.put(
        "/api/admin/engine-config",
        json={
            "levels": [
                {"id": "novice", "strength": 77, "timeout_ms": 1234, "max_depth": 4},  # валидный
                # невалидный id
                {"id": "does_not_exist", "strength": 10, "timeout_ms": 1000, "max_depth": 4},
            ],
            "nnue": True,
        },
    )
    assert r.status_code == 422

    # novice НЕ изменился
    after = (await client.get("/api/admin/engine-config")).json()
    after_novice = next(lv for lv in after["levels"] if lv["id"] == "novice")
    assert after_novice["strength"] == orig_strength
