from app.auth import bump_token_epoch


async def _seed_admin(app):
    from app.dal import users as dal

    async with app.state.sessionmaker() as s:
        await dal.create_user(s, "admin", "pw", role="admin")
        await s.commit()


async def test_health(client):
    assert (await client.get("/api/health")).json() == {"ok": True}


async def test_login_me_logout(app, client):
    await _seed_admin(app)
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert client.cookies.get("renju_token")
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "admin"
    await client.post("/api/auth/logout")
    client.cookies.clear()  # cookie снят → /me даёт 401
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_me_requires_cookie(client):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_epoch_revocation(app, client):
    await _seed_admin(app)
    await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert (await client.get("/api/auth/me")).status_code == 200
    async with app.state.sessionmaker() as s:  # отозвать: bump epoch
        from app.dal import users as dal

        u = await dal.get_user_by_username(s, "admin")
        assert u is not None
        await bump_token_epoch(s, u.id)
        await s.commit()
    assert (await client.get("/api/auth/me")).status_code == 401  # старый токен мёртв
