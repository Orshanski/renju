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
    # Зовём эндпоинт напрямую и читаем gen() с таймаутом — буфер детерминирован.

    cookies = dict(client.cookies)
    settings = app.state.settings

    # Создаём минимальный Request с cookie для get_current_user
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/api/games/{gid}/events",
        "query_string": b"since=0",
        "headers": [
            (b"cookie", f"{settings.cookie_name}={cookies[settings.cookie_name]}".encode())
        ],
        "app": app,
    }
    from starlette.requests import Request as SRequest

    request = SRequest(scope)

    from app.routers.games import events as events_handler

    resp = await events_handler(game_id=gid, request=request, since=0)

    # Читаем данные из тела StreamingResponse с таймаутом
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
