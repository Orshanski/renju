import pytest


@pytest.fixture
async def app_with_spa(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("RENJU_FRONTEND_DIST", str(dist))
    import app.models.game  # noqa: F401
    import app.models.user  # noqa: F401 — обе модели в metadata до create_all (как conftest.app)
    from app.app_factory import create_app
    from app.config import Settings
    from app.db.base import Base

    application = create_app(Settings())
    async with application.router.lifespan_context(application):
        async with application.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield application


@pytest.fixture
async def spa_client(app_with_spa):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app_with_spa), base_url="http://t") as c:
        yield c


async def test_root_serves_index(spa_client):
    r = await spa_client.get("/")
    assert r.status_code == 200 and "id=root" in r.text


async def test_unknown_client_route_serves_index(spa_client):
    r = await spa_client.get("/login")
    assert r.status_code == 200 and "id=root" in r.text


async def test_asset_served(spa_client):
    r = await spa_client.get("/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text


async def test_unknown_api_is_404_json_not_index(spa_client):
    r = await spa_client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert "id=root" not in r.text  # НЕ SPA-fallback; JSON-ошибка


async def test_health_still_json(spa_client):
    r = await spa_client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


async def test_existing_api_get_wins_over_catchall(spa_client):
    # реальный GET-роут /api/auth/me без куки → 401 JSON, НЕ SPA-fallback:
    # доказывает, что зарегистрированные раньше /api/*-GET-роуты матчатся прежде catch-all.
    r = await spa_client.get("/api/auth/me")
    assert r.status_code == 401
    assert "id=root" not in r.text
