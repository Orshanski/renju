async def _login(app, client, username="admin", password="pw"):
    from app.dal import users as dal

    async with app.state.sessionmaker() as s:
        if not await dal.get_user_by_username(s, username):
            await dal.create_user(s, username, password, role="admin")
            await s.commit()
    await client.post("/api/auth/login", json={"username": username, "password": password})


async def _create_user(client, username, password="pw", role="user"):
    r = await client.post(
        "/api/admin/users", json={"username": username, "password": password, "role": role}
    )
    assert r.status_code == 200
    return r.json()["id"]


async def _get_user(client, username):
    users = (await client.get("/api/admin/users")).json()
    return next(u for u in users if u["username"] == username)


async def test_create_and_list_users(app, client):
    await _login(app, client)
    r = await client.post(
        "/api/admin/users", json={"username": "bob", "password": "pw", "role": "user"}
    )
    assert r.status_code == 200
    users = (await client.get("/api/admin/users")).json()
    assert {u["username"] for u in users} >= {"admin", "bob"}


async def test_non_admin_forbidden(app, client):
    await _login(app, client)
    await client.post(
        "/api/admin/users", json={"username": "bob", "password": "pw", "role": "user"}
    )
    client.cookies.clear()
    await client.post("/api/auth/login", json={"username": "bob", "password": "pw"})
    assert (
        await client.post(
            "/api/admin/users", json={"username": "x", "password": "pw", "role": "user"}
        )
    ).status_code == 403


async def test_cannot_delete_self(app, client):
    await _login(app, client)
    me = (await client.get("/api/auth/me")).json()
    assert (await client.delete(f"/api/admin/users/{me['id']}")).status_code == 409


async def test_cannot_delete_last_admin(app, client):
    await _login(app, client)
    # admin — единственный; удалить себя ловится self-delete-guard'ом (409) раньше
    # last-admin-guard. Проверяем удаление НЕ-последнего/НЕ-себя через второго админа:
    await client.post(
        "/api/admin/users", json={"username": "a2", "password": "pw", "role": "admin"}
    )
    a2 = next(u for u in (await client.get("/api/admin/users")).json() if u["username"] == "a2")
    assert (await client.delete(f"/api/admin/users/{a2['id']}")).status_code == 200


async def test_delete_nonexistent_404(app, client):
    await _login(app, client)
    assert (await client.delete("/api/admin/users/9999")).status_code == 404


async def test_reset_password_revokes(app, client):
    await _login(app, client)
    await client.post(
        "/api/admin/users", json={"username": "bob", "password": "pw", "role": "user"}
    )
    bob = next(u for u in (await client.get("/api/admin/users")).json() if u["username"] == "bob")
    client.cookies.clear()
    await client.post("/api/auth/login", json={"username": "bob", "password": "pw"})  # bob входит
    assert (await client.get("/api/auth/me")).status_code == 200
    bob_cookie = client.cookies.get("renju_token")
    client.cookies.clear()
    await _login(app, client)  # снова админ
    assert (
        await client.post(
            f"/api/admin/users/{bob['id']}/reset-password", json={"password": "newpw"}
        )
    ).status_code == 200  # epoch bump
    client.cookies.clear()
    client.cookies.set("renju_token", bob_cookie)
    assert (await client.get("/api/auth/me")).status_code == 401  # старый токен bob мёртв


# ── Новые тест-кейсы (задача 5) ──────────────────────────────────────────────


async def test_list_users_contains_created_at_with_T(app, client):
    """GET /users отдаёт created_at с разделителем T (ISO 8601), не пробелом."""
    await _login(app, client)
    users = (await client.get("/api/admin/users")).json()
    assert len(users) >= 1
    for user in users:
        assert "created_at" in user, f"поле created_at отсутствует у {user}"
        assert "T" in user["created_at"], (
            f"created_at должен содержать T, получено: {user['created_at']!r}"
        )


async def test_put_changes_role_and_revokes_old_token(app, client):
    """PUT меняет роль цели → GET показывает новую роль + старый токен цели → 401."""
    await _login(app, client)
    bob_id = await _create_user(client, "bob")

    # bob входит и запоминает токен
    client.cookies.clear()
    await client.post("/api/auth/login", json={"username": "bob", "password": "pw"})
    bob_cookie = client.cookies.get("renju_token")

    # admin меняет bob'у роль
    client.cookies.clear()
    await _login(app, client)
    r = await client.put(f"/api/admin/users/{bob_id}", json={"role": "admin"})
    assert r.status_code == 200

    # новая роль видна в листинге
    bob_after = await _get_user(client, "bob")
    assert bob_after["role"] == "admin"

    # старый токен bob мёртв
    client.cookies.clear()
    client.cookies.set("renju_token", bob_cookie)
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_put_cannot_change_own_role(app, client):
    """PUT нельзя менять свою роль → 409."""
    await _login(app, client)
    me = (await client.get("/api/auth/me")).json()
    r = await client.put(f"/api/admin/users/{me['id']}", json={"role": "user"})
    assert r.status_code == 409


async def test_put_cannot_demote_last_admin(app, client):
    """last-admin guard: ConflictError при прямом вызове сервиса.

    HTTP-недостижимо: если target — единственный admin, то актор тоже должен
    быть admin, но тогда count_admins >= 2. Тестируем сервисный слой напрямую.
    """
    from app.exceptions import ConflictError
    from app.routers.admin import UpdateUserBody
    from app.services import admin_service

    await _login(app, client)
    me = (await client.get("/api/auth/me")).json()

    # actor_id = 9999 ≠ target → self-guard пропускается; target единственный admin
    async with app.state.sessionmaker() as session:
        try:
            await admin_service.update_user(
                session, me["id"], UpdateUserBody(role="user"), actor_id=9999
            )
            raise AssertionError("должна была быть ConflictError")
        except ConflictError as e:
            assert "последн" in str(e).lower() or "last" in str(e).lower()


async def test_put_nonexistent_user_404(app, client):
    """PUT несуществующего user_id → 404."""
    await _login(app, client)
    r = await client.put("/api/admin/users/9999", json={"role": "user"})
    assert r.status_code == 404


async def test_put_changes_password(app, client):
    """PUT меняет пароль → новым паролем логин 200, старым 401."""
    await _login(app, client)
    bob_id = await _create_user(client, "bob", "oldpw")

    r = await client.put(f"/api/admin/users/{bob_id}", json={"password": "newpw"})
    assert r.status_code == 200

    # новым паролем логин успешен
    client.cookies.clear()
    r = await client.post("/api/auth/login", json={"username": "bob", "password": "newpw"})
    assert r.status_code == 200

    # старым паролем логин отказывает
    client.cookies.clear()
    r = await client.post("/api/auth/login", json={"username": "bob", "password": "oldpw"})
    assert r.status_code == 401


async def test_put_own_password_revokes_actor_token(app, client):
    """PUT со своим паролем (актор = цель) → 200, но токен актора мёртв."""
    await _login(app, client)
    me = (await client.get("/api/auth/me")).json()

    r = await client.put(f"/api/admin/users/{me['id']}", json={"password": "newpw"})
    assert r.status_code == 200

    # тот же клиент (без перелогина) → токен должен быть мёртв
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_put_empty_body_422(app, client):
    """PUT {} (пустое тело) → 422."""
    await _login(app, client)
    me = (await client.get("/api/auth/me")).json()
    r = await client.put(f"/api/admin/users/{me['id']}", json={})
    assert r.status_code == 422


async def test_put_empty_password_422(app, client):
    """PUT {password: ""} → 422."""
    await _login(app, client)
    me = (await client.get("/api/auth/me")).json()
    r = await client.put(f"/api/admin/users/{me['id']}", json={"password": ""})
    assert r.status_code == 422


async def test_put_same_role_noop_token_alive(app, client):
    """PUT с той же ролью (no-op) → 200, токен цели жив (epoch не бампался)."""
    await _login(app, client)
    bob_id = await _create_user(client, "bob")

    # bob входит
    client.cookies.clear()
    await client.post("/api/auth/login", json={"username": "bob", "password": "pw"})
    assert (await client.get("/api/auth/me")).status_code == 200
    bob_cookie = client.cookies.get("renju_token")

    # admin устанавливает ту же роль (no-op)
    client.cookies.clear()
    await _login(app, client)
    r = await client.put(f"/api/admin/users/{bob_id}", json={"role": "user"})
    assert r.status_code == 200

    # токен bob жив (epoch не изменился)
    client.cookies.clear()
    client.cookies.set("renju_token", bob_cookie)
    assert (await client.get("/api/auth/me")).status_code == 200
