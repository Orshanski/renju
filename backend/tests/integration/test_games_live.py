async def test_create_and_move_live_engine(app, client, games_api, rapfi_paths):
    # app поднял живой RapfiAdapter в lifespan — НЕ подменяем (rapfi_paths скипает без бинаря)
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    ).json()["id"]
    # человек мог выпасть чёрным → ход за движком в фоне; ждём оседания (живой движок ~секунды)
    st = await games_api.wait_settled(client, gid, tries=120, delay=0.25)
    assert st["status"] == "awaiting_move"
    n0 = len(st["moves"])
    pt = games_api.free_move(st)  # свободная легальная клетка зоны (с учётом реальных фолов)
    await client.post(f"/api/games/{gid}/move", json={"x": pt[0], "y": pt[1]})
    st = await games_api.wait_settled(client, gid, tries=120, delay=0.25)  # реальный ответ движка
    assert len(st["moves"]) >= n0 + 2 or st["status"].startswith("finished")
