import pytest

from app.auth import AuthError
from app.exceptions import NotFoundError
from app.routers.games import events as events_handler


def _events_request(app, gid, cookie_value):
    """Синтетический Starlette Request на SSE-роут с заданной cookie (или без неё, если None)."""
    from starlette.requests import Request as SRequest

    settings = app.state.settings
    headers = []
    if cookie_value is not None:
        headers.append((b"cookie", f"{settings.cookie_name}={cookie_value}".encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/api/games/{gid}/events",
        "query_string": b"since=0",
        "headers": headers,
        "app": app,
    }
    return SRequest(scope)


def _cookie_for(client, app):
    """Текущий auth-токен из cookie-jar клиента (после seed_login)."""
    return dict(client.cookies)[app.state.settings.cookie_name]


async def test_sse_replays_buffered_events(app, client, games_api):
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    st = await games_api.wait_settled(client, gid)
    # гарантируем события в буфере хаба: подаём ход → фоновый advance публикует move/status
    pt = games_api.free_move(st)
    await client.post(f"/api/games/{gid}/move", json={"x": pt[0], "y": pt[1]})
    await games_api.wait_settled(client, gid)

    # Проверяем реплей напрямую через StreamingResponse: httpx ASGITransport не поддерживает
    # partial-read SSE (awaits полного завершения ASGI-приложения до выдачи тела).
    # Зовём эндпоинт напрямую и читаем gen() — буфер детерминирован.
    request = _events_request(app, gid, _cookie_for(client, app))
    resp = await events_handler(game_id=gid, request=request, since=0)

    got: list[str] = []
    buffer = ""
    async for chunk in resp.body_iterator:
        if isinstance(chunk, (bytes, memoryview)):
            buffer += bytes(chunk).decode()
        else:
            buffer += chunk
        for line in buffer.split("\n"):
            if line.startswith("data:"):
                got.append(line)
        if got:
            break

    assert got  # хотя бы одно событие (move/status) из буфера


async def test_sse_missing_cookie_raises_auth_error(app, client, games_api):
    # Нет/битая cookie → AuthError (middleware смаппил бы в 401). Партию создавать не нужно —
    # get_current_user падает раньше get_game.
    app.state.adapter = games_api.FakeAdapter()
    request = _events_request(app, "any-game-id", cookie_value="garbage-token")
    with pytest.raises(AuthError):
        await events_handler(game_id="any-game-id", request=request, since=0)


async def test_sse_foreign_user_raises_not_found(app, client, games_api):
    # Cookie ЧУЖОГО (bob) на партию alice → NotFoundError (middleware смаппил бы в 404,
    # скрывая существование партии). bob не участник → get_game бросит NotFoundError.
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)  # alice — владелец
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)

    await games_api.seed_login(app, client, username="bob")  # cookie теперь bob
    request = _events_request(app, gid, _cookie_for(client, app))
    with pytest.raises(NotFoundError):
        await events_handler(game_id=gid, request=request, since=0)
