from app.game.controllers import Engine
from app.game.event_hub import InMemoryEventHub
from app.game.repository import InMemoryGameRepository
from app.game.service import GameService
from app.game.settings_repository import InMemorySettingsRepository

# Замороженный снимок «мастер»-уровня для тестов
_MASTER = Engine(level_id="master", strength=90, timeout_ms=6000, nnue=True)
# Сериализованный JSON (для использования в controllers dict напрямую)
_MASTER_JSON = {
    "kind": "engine",
    "level_id": "master",
    "strength": 90,
    "timeout_ms": 6000,
    "nnue": True,
}


class FakeAdapter:
    def __init__(self):
        self.forbid = [(3, 3)]
        self.move = (8, 8)
        self.undo_syncs = []

    async def forbidden_points(self, game_id, moves, *, level_tag="-", nnue=None):
        return list(self.forbid)

    async def compute_move(
        self, game_id, moves, params, allowed_zone=None, *, level_tag="-", nnue=None
    ):
        return self.move

    async def sync_after_undo(self, game_id, moves, *, level_tag="-"):
        self.undo_syncs.append((game_id, [tuple(m) for m in moves], level_tag))


def _svc(adapter=None, settings_repo=None):
    return GameService(
        repo=InMemoryGameRepository(),
        hub=InMemoryEventHub(),
        adapter=adapter or FakeAdapter(),
        settings_repo=settings_repo or InMemorySettingsRepository(),
    )


async def _create_game(svc, owner_id=1, human_color="black"):
    """Хелпер: create_game с замороженным _MASTER-снимком."""
    return await svc.create_game(owner_id=owner_id, engine_ctl=_MASTER, human_color=human_color)


async def test_fouls_memoized_one_engine_call():
    svc = _svc()
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points

    async def counting(game_id, moves, *, level_tag="-", nnue=None):
        svc._adapter.calls += 1
        return await orig(game_id, moves, level_tag=level_tag)

    svc._adapter.forbidden_points = counting
    from app.models.game import Game

    g = Game(
        id="g",
        owner_id=1,
        controllers={},
        moves=[[7, 7], [8, 8]],
        status="awaiting_move",
        undo_count=0,
        forbidden_log={},
    )
    f1 = await svc.fouls(g, g.moves)  # len 2 (чёрные) → движок, запись
    f2 = await svc.fouls(g, g.moves)  # из лога
    assert f1 == [(3, 3)] and f2 == [(3, 3)] and svc._adapter.calls == 1
    assert g.forbidden_log["2"] == [[3, 3]]


async def test_fouls_white_to_move_empty_no_engine():
    svc = _svc()
    svc._adapter.calls = 0
    from app.models.game import Game

    g = Game(
        id="g",
        owner_id=1,
        controllers={},
        moves=[[7, 7]],
        status="awaiting_move",
        undo_count=0,
        forbidden_log={},
    )
    assert await svc.fouls(g, g.moves) == []  # len 1 (белые) → []


async def test_create_hve_human_black_pending_engine():
    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="black")
    # центр (ход 1 = чёрные) предзаполнен = ход человека; ход 2 за движком-белым → ждём фон
    assert g.moves == [[7, 7]] and g.status == "opponent_thinking"


async def test_create_hve_human_white_awaits_human():
    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="white")
    # центр = ход 1 = чёрные = движок (предзаполнен); ход 2 за человеком-белым
    assert g.moves == [[7, 7]] and g.status == "awaiting_move"


async def test_advance_drives_engine_move():
    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="black")
    await svc.advance(g)  # «фон»: движок-белый ходит 2-м
    assert g.moves == [[7, 7], [8, 8]] and g.status == "awaiting_move"


async def test_neutrality_both_interactive_pvp_no_autoplay():
    svc = _svc()
    from app.models.game import Game

    g = Game(
        id="g",
        owner_id=1,
        moves=[[7, 7]],
        undo_count=0,
        forbidden_log={},
        controllers={
            "black": {"kind": "user", "user_id": 1},
            "white": {"kind": "user", "user_id": 2},
        },
        status="awaiting_move",
    )
    await svc._repo.create(g)
    await svc.advance(g)
    assert g.moves == [[7, 7]] and g.status == "awaiting_move"  # advance НЕ ходит сам


async def test_advance_engine_error_publishes_error_event():
    from app.rapfi.adapter import EngineError

    svc = _svc()

    async def boom(game_id, moves, params, allowed_zone=None, *, level_tag="-", nnue=None):
        raise EngineError("twice")

    svc._adapter.compute_move = boom
    g = await _create_game(svc, owner_id=1, human_color="black")
    assert g.status == "opponent_thinking"
    await svc.advance(g)  # движок падает → error-событие, статус НЕ меняется (§4.8 доиграет позже)
    assert g.status == "opponent_thinking"
    assert any(e["type"] == "error" for e in svc._hub._log.get(g.id, []))


async def test_submit_move_then_engine_replies_via_advance():
    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="white")
    svc._adapter.move = (5, 5)
    g = await svc.submit_move(g.id, user_id=1, point=(6, 6))  # ход 2 белые (человек)
    assert g.moves == [[7, 7], [6, 6]] and g.status == "opponent_thinking"  # ждём движок
    await svc.advance(g)  # «фон»: движок-чёрный ходит 3-м
    assert g.moves == [[7, 7], [6, 6], [5, 5]] and g.status == "awaiting_move"


async def test_submit_not_your_turn_pvp_form():
    import pytest

    from app.domain.errors import MoveRejected, MoveRejectReason
    from app.models.game import Game

    svc = _svc()
    g = Game(
        id="g",
        owner_id=1,
        moves=[[7, 7]],
        undo_count=0,
        forbidden_log={},
        controllers={
            "black": {"kind": "user", "user_id": 1},
            "white": {"kind": "user", "user_id": 2},
        },
        status="awaiting_move",
    )
    await svc._repo.create(g)
    # ход 2 = белые = user 2; чёрный (user 1, участник) подаёт не в свою очередь
    with pytest.raises(MoveRejected) as e:
        await svc.submit_move("g", user_id=1, point=(6, 6))
    assert e.value.reason is MoveRejectReason.NOT_YOUR_TURN


async def test_submit_foreign_user_not_found():
    import pytest

    from app.exceptions import NotFoundError

    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="black")
    with pytest.raises(NotFoundError):  # user 2 не участник одиночной HvE-партии
        await svc.submit_move(g.id, user_id=2, point=(6, 6))


async def test_undo_pure_replay_no_engine():
    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="white")
    svc._adapter.move = (6, 6)
    g = await svc.submit_move(g.id, user_id=1, point=(8, 8))  # ход 2 белые (реальный ход человека)
    await svc.advance(g)  # «фон»: движок-чёрный ходит 3-м → [[7,7],[8,8],[6,6]]
    assert g.moves == [[7, 7], [8, 8], [6, 6]]
    # форбиды позиций уже в forbidden_log → undo без движка
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points

    async def counting(game_id, m, **kw):
        svc._adapter.calls += 1
        return await orig(game_id, m)

    svc._adapter.forbidden_points = counting
    g = await svc.undo(g.id, user_id=1)
    # откат белых: снимаем ход 3 (движок) и ход 2 (человек) → назад к [[7,7]]
    assert g.moves == [[7, 7]] and "2" not in g.forbidden_log and "3" not in g.forbidden_log
    assert svc._adapter.calls == 0  # undo без движка
    assert svc._adapter.undo_syncs == [(g.id, [(7, 7)], "-")]


async def test_advance_recovers_and_is_idempotent():
    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="black")
    # create оставил opponent_thinking (ход 2 за движком); фоновой задачи в юните нет
    assert g.status == "opponent_thinking" and g.moves == [[7, 7]]
    await svc.advance(g)  # «восстановление»: движок-белый ходит 2-м
    assert g.moves == [[7, 7], [8, 8]] and g.status == "awaiting_move"
    snapshot = [list(m) for m in g.moves]
    await svc.advance(g)  # повтор — no-op: ход человека-чёрного, advance ждёт подачу
    assert g.moves == snapshot and g.status == "awaiting_move"


async def test_advance_recovery_when_engine_move_already_applied():
    # реальный краш: ход движка УЖЕ закоммичен, но статус застрял opponent_thinking
    # (упали между repo.update(move) и переходом в awaiting_move) → recovery НЕ двигает повторно
    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="black")
    await svc.advance(g)  # движок сходил → [[7,7],[8,8]], awaiting_move (ход человека-чёрного)
    g.status = "opponent_thinking"
    await svc._repo.update(g)  # симулируем застрявший статус
    svc._adapter.calls = 0
    orig = svc._adapter.compute_move

    async def counting(*a, **k):
        svc._adapter.calls += 1
        return await orig(*a, **k)

    svc._adapter.compute_move = counting
    await svc.advance(g)  # позиция = ход человека → advance оседает на awaiting_move без движка
    assert g.moves == [[7, 7], [8, 8]] and g.status == "awaiting_move"
    assert svc._adapter.calls == 0  # движок НЕ дёрнут — ход не задвоен


async def test_get_game_pure_access_check():
    import pytest

    from app.exceptions import NotFoundError

    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="black")
    assert (await svc.get_game(g.id, user_id=1)).id == g.id  # участник — ок
    with pytest.raises(NotFoundError):
        await svc.get_game(g.id, user_id=2)  # чужой → 404
    with pytest.raises(NotFoundError):
        await svc.get_game("missing", user_id=1)
    assert g.status == "opponent_thinking"  # get_game НЕ ходит движком (фон — забота роутера)


async def test_undo_no_engine_even_with_sparse_log():
    # структурная гарантия: undo не зовёт движок, даже если ключ форбидов позиции,
    # на которую приземляется откат, НЕ мемоизирован (sparse log). Старый код (fouls)
    # дёрнул бы forbidden_points на чёрной позиции; прямое чтение лога — нет.
    from app.models.game import Game

    svc = _svc()
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points

    async def counting(game_id, m, **kw):
        svc._adapter.calls += 1
        return await orig(game_id, m)

    svc._adapter.forbidden_points = counting
    g = Game(
        id="g",
        owner_id=1,
        moves=[[7, 7], [8, 8], [9, 9], [10, 10]],
        undo_count=0,
        forbidden_log={},  # НАМЕРЕННО пусто — провоцируем движок у старого кода
        controllers={
            "black": {"kind": "user", "user_id": 1},
            "white": _MASTER_JSON,
        },
        status="awaiting_move",
    )
    await svc._repo.create(g)
    g2 = await svc.undo("g", user_id=1)  # откат чёрного: len4 → new_moves len2 (чёрная позиция)
    assert g2.moves == [[7, 7], [8, 8]] and svc._adapter.calls == 0


async def test_advance_engine_black_does_not_query_fouls():
    from app.models.game import Game

    svc = _svc()
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points

    async def counting(game_id, moves, *, level_tag="-", nnue=None):
        svc._adapter.calls += 1
        return await orig(game_id, moves, level_tag=level_tag)

    svc._adapter.forbidden_points = counting
    g = Game(
        id="g",
        owner_id=1,
        moves=[[7, 7], [8, 8]],
        undo_count=0,
        forbidden_log={},
        controllers={
            "black": _MASTER_JSON,
            "white": {"kind": "user", "user_id": 1},
        },
        status="opponent_thinking",
    )
    await svc._repo.create(g)
    await svc.advance(g)  # движок-чёрный ходит 3-м; фолы для него НЕ запрашиваются
    assert svc._adapter.calls == 0


async def test_eve_advance_drives_both_engine_sides():
    # обе стороны Engine: advance двигает ОБЕ стороны до исхода (нейтральность, спека §Тестирование)
    from app.models.game import Game

    seq = [(6, 6), (6, 7), (7, 5), (8, 7), (8, 5), (9, 7), (9, 5), (5, 7)]

    class _SeqAdapter:
        def __init__(self):
            self.i = 0

        async def forbidden_points(self, game_id, moves, *, level_tag="-", nnue=None):
            return []

        async def compute_move(
            self, game_id, moves, params, allowed_zone=None, *, level_tag="-", nnue=None
        ):
            mv = seq[self.i]
            self.i += 1
            return mv

        async def close(self):
            pass

    svc = _svc(adapter=_SeqAdapter())
    g = Game(
        id="g",
        owner_id=1,
        moves=[[7, 7]],
        undo_count=0,
        forbidden_log={},
        controllers={
            "black": _MASTER_JSON,
            "white": _MASTER_JSON,
        },
        status="opponent_thinking",
    )
    await svc._repo.create(g)
    await svc.advance(g)  # оба контролёра движок → advance двигает обе стороны
    assert g.status == "finished_black"
    assert len(g.moves) == 9  # 8 engine-ходов поверх предзаполненного центра


# ── Retention tests ────────────────────────────────────────────────────────────


async def test_finish_sets_finished_at_and_evicts_over_limit():
    """finished_limit=2; 2 старые завершённые + 3-я доигрывается → vытесняется старейшая."""
    from datetime import datetime, timedelta

    from app.models.game import Game
    from app.models.user_settings import UserSettings

    sr = InMemorySettingsRepository()
    await sr.upsert(
        UserSettings(
            user_id=1,
            current_limit=10,
            current_limit_enabled=True,
            finished_limit=2,
            finished_limit_enabled=True,
        )
    )
    svc = _svc(settings_repo=sr)

    now = datetime(2026, 1, 1, 12, 0, 0)
    ctl_hve = {
        "black": _MASTER_JSON,
        "white": {"kind": "user", "user_id": 1},
    }
    ctl_finished = {
        "black": {"kind": "user", "user_id": 1},
        "white": _MASTER_JSON,
    }

    # Две старые завершённые — засеиваем с явными finished_at
    g_oldest = Game(
        id="old1",
        owner_id=1,
        controllers=ctl_finished,
        moves=[[7, 7], [8, 8], [9, 9], [10, 10], [11, 11]],
        status="finished_black",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=now - timedelta(days=2),
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=2),
    )
    g_older = Game(
        id="old2",
        owner_id=1,
        controllers=ctl_finished,
        moves=[[7, 7], [8, 8], [9, 9], [10, 10], [11, 11]],
        status="finished_black",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=now - timedelta(days=1),
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=1),
    )
    await svc._repo.create(g_oldest)
    await svc._repo.create(g_older)

    # Доигрываем 3-ю через advance: движок-чёрный делает победный ход (11,11)
    svc._adapter.move = (11, 11)
    g_new = Game(
        id="new1",
        owner_id=1,
        controllers=ctl_hve,
        moves=[[7, 7], [0, 0], [8, 8], [0, 1], [9, 9], [0, 2], [10, 10], [0, 3]],
        status="opponent_thinking",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )
    await svc._repo.create(g_new)

    # advance → движок-чёрный ходит и выигрывает (5 в ряд)
    await svc.advance(g_new)

    assert g_new.status == "finished_black", f"Expected finished_black, got {g_new.status}"
    assert g_new.finished_at is not None, "finished_at should be set after finishing"

    # В разделе Завершённые должно остаться ровно 2
    all_games = await svc._repo.list_by_owner(1)
    finished = [g for g in all_games if g.status == "finished_black"]
    assert len(finished) == 2, f"Expected 2 finished: {[g.id for g in finished]}"

    # Удалена именно старейшая (g_oldest)
    ids = {g.id for g in finished}
    assert "old1" not in ids, "Oldest game should have been evicted"
    assert "new1" in ids, "New game should still be present"


async def test_create_evicts_current_over_limit():
    """current_limit=2; 2 текущих + создаём 3-ю → вытесняется самая давно не тронутая."""
    from datetime import datetime, timedelta

    from app.models.game import Game
    from app.models.user_settings import UserSettings

    sr = InMemorySettingsRepository()
    await sr.upsert(
        UserSettings(
            user_id=1,
            current_limit=2,
            current_limit_enabled=True,
            finished_limit=50,
            finished_limit_enabled=True,
        )
    )
    svc = _svc(settings_repo=sr)

    now = datetime(2026, 1, 1, 12, 0, 0)
    ctl = {
        "black": {"kind": "user", "user_id": 1},
        "white": _MASTER_JSON,
    }

    g_stale = Game(
        id="cur1",
        owner_id=1,
        controllers=ctl,
        moves=[[7, 7]],
        status="awaiting_move",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=None,
        created_at=now - timedelta(days=5),
        updated_at=now - timedelta(days=5),  # самая старая по updated_at
    )
    g_newer = Game(
        id="cur2",
        owner_id=1,
        controllers=ctl,
        moves=[[7, 7]],
        status="awaiting_move",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=None,
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=3),
    )
    await svc._repo.create(g_stale)
    await svc._repo.create(g_newer)

    # Создаём 3-ю → вытеснение
    g_third = await _create_game(svc, owner_id=1, human_color="white")

    all_games = await svc._repo.list_by_owner(1)
    current = [g for g in all_games if not g.status.startswith("finished_") and g.favorite is False]
    assert len(current) == 2, f"Expected 2 current: {[g.id for g in current]}"

    ids = {g.id for g in current}
    assert "cur1" not in ids, "Stale game should have been evicted"
    assert g_third.id in ids, "New game should NOT be evicted"


async def test_favorite_only_finished_and_exempt_from_limit():
    """favorite на Завершённой → game.favorite==True, не вытесняется; на Текущей → ConflictError."""
    from datetime import datetime, timedelta

    import pytest

    from app.exceptions import ConflictError
    from app.models.game import Game
    from app.models.user_settings import UserSettings

    sr = InMemorySettingsRepository()
    await sr.upsert(
        UserSettings(
            user_id=1,
            current_limit=10,
            current_limit_enabled=True,
            finished_limit=1,  # лимит 1: без фаворита — вытеснение
            finished_limit_enabled=True,
        )
    )
    svc = _svc(settings_repo=sr)
    now = datetime(2026, 1, 1, 12, 0, 0)
    ctl = {
        "black": {"kind": "user", "user_id": 1},
        "white": _MASTER_JSON,
    }
    moves_finished = [[7, 7], [8, 8], [9, 9], [10, 10], [11, 11]]

    g_fav = Game(
        id="fav1",
        owner_id=1,
        controllers=ctl,
        moves=moves_finished,
        status="finished_black",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=now - timedelta(days=2),
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(days=2),
    )
    g_another = Game(
        id="fin2",
        owner_id=1,
        controllers=ctl,
        moves=moves_finished,
        status="finished_black",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=now - timedelta(days=1),
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=1),
    )
    await svc._repo.create(g_fav)
    await svc._repo.create(g_another)

    # Помечаем g_fav как избранную
    await svc.favorite_game("fav1", user_id=1)

    g_after = await svc._repo.get("fav1")
    assert g_after is not None and g_after.favorite is True

    # Добавляем ещё одну завершённую — лимит=1, но g_fav в FAVORITE разделе, не вытесняется
    g_third = Game(
        id="fin3",
        owner_id=1,
        controllers=ctl,
        moves=moves_finished,
        status="finished_black",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )
    await svc._repo.create(g_third)
    await svc._evict_finished(1)

    # g_fav должна уцелеть (FAVORITE, вне лимита)
    g_fav_check = await svc._repo.get("fav1")
    assert g_fav_check is not None, "Favorite game should NOT be evicted"

    # favorite на Текущей партии → ConflictError
    g_current = Game(
        id="cur_x",
        owner_id=1,
        controllers=ctl,
        moves=[[7, 7]],
        status="awaiting_move",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )
    await svc._repo.create(g_current)
    with pytest.raises(ConflictError):
        await svc.favorite_game("cur_x", user_id=1)


async def test_unfavorite_returns_to_finished_and_rechecks_limit():
    """unfavorite: favorite=False, finished_at НЕ тронут; при превышении лимита — вытеснение."""
    from datetime import datetime, timedelta

    from app.models.game import Game
    from app.models.user_settings import UserSettings

    sr = InMemorySettingsRepository()
    await sr.upsert(
        UserSettings(
            user_id=1,
            current_limit=10,
            current_limit_enabled=True,
            finished_limit=1,  # лимит 1 → при возврате из избранного вытеснение
            finished_limit_enabled=True,
        )
    )
    svc = _svc(settings_repo=sr)
    now = datetime(2026, 1, 1, 12, 0, 0)
    ctl = {
        "black": {"kind": "user", "user_id": 1},
        "white": _MASTER_JSON,
    }
    moves_finished = [[7, 7], [8, 8], [9, 9], [10, 10], [11, 11]]

    g_fav = Game(
        id="fav1",
        owner_id=1,
        controllers=ctl,
        moves=moves_finished,
        status="finished_black",
        undo_count=0,
        forbidden_log={},
        favorite=True,
        finished_at=now - timedelta(days=5),
        created_at=now - timedelta(days=6),
        updated_at=now - timedelta(days=5),
    )
    g_other = Game(
        id="fin2",
        owner_id=1,
        controllers=ctl,
        moves=moves_finished,
        status="finished_black",
        undo_count=0,
        forbidden_log={},
        favorite=False,
        finished_at=now - timedelta(days=1),
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=1),
    )
    await svc._repo.create(g_fav)
    await svc._repo.create(g_other)

    # unfavorite → g_fav возвращается в FINISHED, лимит=1, она старейшая → вытесняется
    await svc.unfavorite_game("fav1", user_id=1)

    g_fav_check = await svc._repo.get("fav1")
    # При лимите=1 и g_fav старейшей по finished_at — она должна быть вытеснена
    assert g_fav_check is None, "Unfavorited oldest game should be evicted when over limit"

    g_other_check = await svc._repo.get("fin2")
    assert g_other_check is not None, "Newer game should survive"
    # finished_at g_other НЕ тронут
    assert g_other_check.finished_at == now - timedelta(days=1)


async def test_delete_game_removes():
    """delete_game владельцем убирает партию; чужим → NotFoundError."""
    import pytest

    from app.exceptions import NotFoundError

    svc = _svc()
    g = await _create_game(svc, owner_id=1, human_color="white")
    gid = g.id

    # чужой → NotFoundError
    with pytest.raises(NotFoundError):
        await svc.delete_game(gid, user_id=99)

    # владелец → удалено
    await svc.delete_game(gid, user_id=1)
    assert await svc._repo.get(gid) is None


async def test_enforce_limits_trims_both_sections():
    """enforce_limits подрезает оба раздела до лимита."""
    from datetime import datetime, timedelta

    from app.models.game import Game
    from app.models.user_settings import UserSettings

    sr = InMemorySettingsRepository()
    await sr.upsert(
        UserSettings(
            user_id=1,
            current_limit=1,
            current_limit_enabled=True,
            finished_limit=1,
            finished_limit_enabled=True,
        )
    )
    svc = _svc(settings_repo=sr)
    now = datetime(2026, 1, 1, 12, 0, 0)
    ctl = {
        "black": {"kind": "user", "user_id": 1},
        "white": _MASTER_JSON,
    }

    # 2 текущих
    for i, delta in enumerate([5, 3]):
        g = Game(
            id=f"cur{i}",
            owner_id=1,
            controllers=ctl,
            moves=[[7, 7]],
            status="awaiting_move",
            undo_count=0,
            forbidden_log={},
            favorite=False,
            finished_at=None,
            created_at=now - timedelta(days=delta + 1),
            updated_at=now - timedelta(days=delta),
        )
        await svc._repo.create(g)

    # 2 завершённых
    for i, delta in enumerate([4, 2]):
        g = Game(
            id=f"fin{i}",
            owner_id=1,
            controllers=ctl,
            moves=[[7, 7], [8, 8], [9, 9], [10, 10], [11, 11]],
            status="finished_black",
            undo_count=0,
            forbidden_log={},
            favorite=False,
            finished_at=now - timedelta(days=delta),
            created_at=now - timedelta(days=delta + 1),
            updated_at=now - timedelta(days=delta),
        )
        await svc._repo.create(g)

    await svc.enforce_limits(1)

    all_games = await svc._repo.list_by_owner(1)
    current_remaining = [g for g in all_games if g.status == "awaiting_move"]
    finished_remaining = [g for g in all_games if g.status == "finished_black"]

    assert len(current_remaining) == 1, f"Expected 1 current, got {len(current_remaining)}"
    assert len(finished_remaining) == 1, f"Expected 1 finished, got {len(finished_remaining)}"

    # Выжившие — новейшие
    assert current_remaining[0].id == "cur1"  # delta=3, newer
    assert finished_remaining[0].id == "fin1"  # delta=2, newer


async def test_undo_resets_finished_at():
    """Партия доиграна (finished_at проставлен) → undo → finished_at снова None."""
    from datetime import datetime

    from app.models.game import Game

    svc = _svc()

    # Партия в состоянии finished с проставленным finished_at
    now = datetime(2026, 1, 1, 12, 0, 0)
    g = Game(
        id="g",
        owner_id=1,
        controllers={
            "black": {"kind": "user", "user_id": 1},
            "white": _MASTER_JSON,
        },
        moves=[[7, 7], [8, 8], [9, 9], [10, 10], [11, 11]],
        status="finished_black",
        undo_count=0,
        forbidden_log={"4": [], "2": [], "0": []},
        favorite=False,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )
    await svc._repo.create(g)

    g2 = await svc.undo("g", user_id=1)
    assert g2.finished_at is None, "undo должен сбросить finished_at в None"
