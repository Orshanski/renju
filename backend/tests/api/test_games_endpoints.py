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


# ---------------------------------------------------------------------------
# Task 5: delete / favorite / unfavorite / summary
# ---------------------------------------------------------------------------


async def test_delete_game_owner(app, client, games_api):
    """Владелец удаляет свою партию → 204, партия пропадает из списка."""
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)
    r = await client.delete(f"/api/games/{gid}")
    assert r.status_code == 204
    # партия должна исчезнуть — GET возвращает 404
    r2 = await client.get(f"/api/games/{gid}")
    assert r2.status_code == 404


async def test_delete_game_not_found(app, client, games_api):
    """Несуществующая партия → 404."""
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    r = await client.delete("/api/games/nonexistent-id")
    assert r.status_code == 404


async def test_delete_game_other_user(app, client, games_api):
    """Чужая партия → 404 (не раскрываем существование)."""
    app.state.adapter = games_api.FakeAdapter()
    # alice создаёт партию
    await games_api.seed_login(app, client, username="alice")
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    # bob пытается удалить
    await games_api.seed_login(app, client, username="bob")
    r = await client.delete(f"/api/games/{gid}")
    assert r.status_code == 404


async def test_favorite_finished_game(app, client, games_api):
    """Завершённая партия: favorite → 200, тело ответа `true`."""
    from app.models.game import Game

    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)  # дождаться хода движка
    # принудительно завершаем партию
    async with app.state.sessionmaker() as s:
        g = await s.get(Game, gid)
        g.status = "finished_black"
        await s.commit()
    r = await client.post(f"/api/games/{gid}/favorite")
    assert r.status_code == 200
    assert r.json() is True
    # партия реально попала в раздел «Избранное»
    fav = (await client.get("/api/games/summary?section=favorite")).json()
    assert any(i["id"] == gid for i in fav)


async def test_favorite_unfinished_game_409(app, client, games_api):
    """Незавершённая партия (awaiting_move/opponent_thinking) → 409."""
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)
    r = await client.post(f"/api/games/{gid}/favorite")
    assert r.status_code == 409


async def test_unfavorite_game(app, client, games_api):
    """unfavorite → 200, тело `true`; партия возвращается в раздел «Завершённые»."""
    from app.models.game import Game

    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)  # дождаться хода движка
    # завершаем и помечаем избранной в БД
    async with app.state.sessionmaker() as s:
        g = await s.get(Game, gid)
        g.status = "finished_black"
        g.favorite = True
        await s.commit()
    r = await client.post(f"/api/games/{gid}/unfavorite")
    assert r.status_code == 200
    assert r.json() is True
    # ушла из «Избранного», вернулась в «Завершённые»
    fav = (await client.get("/api/games/summary?section=favorite")).json()
    fin = (await client.get("/api/games/summary?section=finished")).json()
    assert not any(i["id"] == gid for i in fav)
    assert any(i["id"] == gid for i in fin)


async def test_summary_current_fields(app, client, games_api):
    """GET /api/games/summary?section=current: summary-DTO с позицией (moves) для
    мини-доски карточки, но без прочих тяжёлых полей (winning_line/cursor/forbidden)."""
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)

    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)

    r = await client.get("/api/games/summary?section=current")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list) and len(items) >= 1

    item = next(i for i in items if i["id"] == gid)
    # обязательные лёгкие поля
    for field in (
        "id",
        "status",
        "section",
        "level_id",
        "your_color",
        "move_count",
        "moves",
        "favorite",
        "updated_at",
        "finished_at",
    ):
        assert field in item

    # move_count — число (не массив)
    assert isinstance(item["move_count"], int)

    # moves — позиция для мини-доски: список координат, согласован со счётчиком
    assert isinstance(item["moves"], list)
    assert len(item["moves"]) == item["move_count"]
    assert all(isinstance(p, list) and len(p) == 2 for p in item["moves"])

    # прочие тяжёлые поля по-прежнему ОТСУТСТВУЮТ
    assert "winning_line" not in item
    assert "cursor" not in item
    assert "forbidden" not in item

    # текущая незавершённая партия → section=current
    assert item["section"] == "current"
    assert item["level_id"] == "master"


async def test_summary_filter_by_section(app, client, games_api):
    """section фильтрует: current → только текущие, finished/favorite — свои разделы."""
    from app.models.game import Game

    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)

    async def make_game():
        gid = (
            await client.post(
                "/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}}
            )
        ).json()["id"]
        await games_api.wait_settled(client, gid)
        return gid

    cur = await make_game()  # остаётся current
    fin = await make_game()  # завершим
    fav = await make_game()  # завершим + в избранное

    async with app.state.sessionmaker() as s:
        g_fin = await s.get(Game, fin)
        g_fin.status = "finished_black"
        g_fav = await s.get(Game, fav)
        g_fav.status = "finished_white"
        g_fav.favorite = True
        await s.commit()

    cur_ids = {i["id"] for i in (await client.get("/api/games/summary?section=current")).json()}
    fin_ids = {i["id"] for i in (await client.get("/api/games/summary?section=finished")).json()}
    fav_ids = {i["id"] for i in (await client.get("/api/games/summary?section=favorite")).json()}

    assert cur in cur_ids and fin not in cur_ids and fav not in cur_ids
    assert fin in fin_ids and cur not in fin_ids and fav not in fin_ids
    assert fav in fav_ids and cur not in fav_ids and fin not in fav_ids


async def test_summary_invalid_section_422(app, client, games_api):
    """Невалидный section → 422 (валидация enum FastAPI)."""
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    r = await client.get("/api/games/summary?section=bogus")
    assert r.status_code == 422


async def test_summary_missing_section_422(app, client, games_api):
    """section обязателен → без него 422."""
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    r = await client.get("/api/games/summary")
    assert r.status_code == 422


async def test_favorite_does_not_bump_updated_at(app, client, games_api):
    """Пометка в избранное НЕ меняет updated_at (бампается только реальным ходом)."""
    from app.models.game import Game

    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    await games_api.wait_settled(client, gid)
    async with app.state.sessionmaker() as s:
        g = await s.get(Game, gid)
        g.status = "finished_black"
        await s.commit()

    before = next(
        i
        for i in (await client.get("/api/games/summary?section=finished")).json()
        if i["id"] == gid
    )["updated_at"]

    assert (await client.post(f"/api/games/{gid}/favorite")).status_code == 200

    after = next(
        i
        for i in (await client.get("/api/games/summary?section=favorite")).json()
        if i["id"] == gid
    )["updated_at"]

    assert before == after  # favorite не трогает «когда обновлено»


async def test_real_move_bumps_updated_at(app, client, games_api):
    """Реальный ход человека бампает updated_at."""
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "master"}})
    ).json()["id"]
    st = await games_api.wait_settled(client, gid)
    assert st["status"] == "awaiting_move"

    before = next(
        i for i in (await client.get("/api/games/summary?section=current")).json() if i["id"] == gid
    )["updated_at"]

    pt = games_api.free_move(st)
    mv = await client.post(f"/api/games/{gid}/move", json={"x": pt[0], "y": pt[1]})
    assert mv.status_code == 202
    await games_api.wait_settled(client, gid)

    after = next(
        i for i in (await client.get("/api/games/summary?section=current")).json() if i["id"] == gid
    )["updated_at"]

    assert after > before  # ход обновил «когда обновлено»
