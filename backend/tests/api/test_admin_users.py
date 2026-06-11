async def _login(app, client, username="admin", password="pw"):
    from app.dal import users as dal

    async with app.state.sessionmaker() as s:
        if not await dal.get_user_by_username(s, username):
            await dal.create_user(s, username, password, role="admin")
            await s.commit()
    await client.post("/api/auth/login", json={"username": username, "password": password})


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
