from app.game.event_hub import InMemoryEventHub
from app.game.repository import InMemoryGameRepository
from app.game.service import GameService


class FakeAdapter:
    def __init__(self):
        self.forbid = [(3, 3)]
        self.move = (8, 8)

    async def forbidden_points(self, game_id, moves, *, level_tag="-"):
        return list(self.forbid)

    async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
        return self.move


def _svc(adapter=None):
    return GameService(
        repo=InMemoryGameRepository(),
        hub=InMemoryEventHub(),
        adapter=adapter or FakeAdapter(),
        levels={"master": object()},
    )


async def test_fouls_memoized_one_engine_call():
    svc = _svc()
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points

    async def counting(game_id, moves, *, level_tag="-"):
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
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    # центр (ход 1 = чёрные) предзаполнен = ход человека; ход 2 за движком-белым → ждём фон
    assert g.moves == [[7, 7]] and g.status == "opponent_thinking"


async def test_create_hve_human_white_awaits_human():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="white")
    # центр = ход 1 = чёрные = движок (предзаполнен); ход 2 за человеком-белым
    assert g.moves == [[7, 7]] and g.status == "awaiting_move"


async def test_advance_drives_engine_move():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
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

    async def boom(game_id, moves, params, allowed_zone=None, *, level_tag="-"):
        raise EngineError("twice")

    svc._adapter.compute_move = boom
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    assert g.status == "opponent_thinking"
    await svc.advance(g)  # движок падает → error-событие, статус НЕ меняется (§4.8 доиграет позже)
    assert g.status == "opponent_thinking"
    assert any(e["type"] == "error" for e in svc._hub._log.get(g.id, []))


async def test_submit_move_then_engine_replies_via_advance():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="white")
    svc._adapter.move = (5, 5)
    g = await svc.submit_move(g.id, user_id=1, point=(6, 6))  # ход 2 белые (человек)
    assert g.moves == [[7, 7], [6, 6]] and g.status == "opponent_thinking"  # ждём движок
    await svc.advance(g)  # «фон»: движок-чёрный ходит 3-м
    assert g.moves == [[7, 7], [6, 6], [5, 5]] and g.status == "awaiting_move"


async def test_submit_not_your_turn_pvp_form():
    import pytest

    from app.domain.values import MoveRejected, MoveRejectReason
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
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
    with pytest.raises(NotFoundError):  # user 2 не участник одиночной HvE-партии
        await svc.submit_move(g.id, user_id=2, point=(6, 6))


async def test_undo_pure_replay_no_engine():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="white")
    svc._adapter.move = (6, 6)
    g = await svc.submit_move(g.id, user_id=1, point=(8, 8))  # ход 2 белые (реальный ход человека)
    await svc.advance(g)  # «фон»: движок-чёрный ходит 3-м → [[7,7],[8,8],[6,6]]
    assert g.moves == [[7, 7], [8, 8], [6, 6]]
    # форбиды позиций уже в forbidden_log → undo без движка
    svc._adapter.calls = 0
    orig = svc._adapter.forbidden_points

    async def counting(game_id, m):
        svc._adapter.calls += 1
        return await orig(game_id, m)

    svc._adapter.forbidden_points = counting
    g = await svc.undo(g.id, user_id=1)
    # откат белых: снимаем ход 3 (движок) и ход 2 (человек) → назад к [[7,7]]
    assert g.moves == [[7, 7]] and "2" not in g.forbidden_log and "3" not in g.forbidden_log
    assert svc._adapter.calls == 0  # undo без движка


async def test_advance_recovers_and_is_idempotent():
    svc = _svc()
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
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
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
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
    g = await svc.create_game(owner_id=1, opponent_level="master", human_color="black")
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

    async def counting(game_id, m):
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
            "white": {"kind": "engine", "level_id": "master"},
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

    async def counting(game_id, moves, *, level_tag="-"):
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
            "black": {"kind": "engine", "level_id": "master"},
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

        async def forbidden_points(self, game_id, moves, *, level_tag="-"):
            return []

        async def compute_move(self, game_id, moves, params, allowed_zone=None, *, level_tag="-"):
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
            "black": {"kind": "engine", "level_id": "master"},
            "white": {"kind": "engine", "level_id": "master"},
        },
        status="opponent_thinking",
    )
    await svc._repo.create(g)
    await svc.advance(g)  # оба контролёра движок → advance двигает обе стороны
    assert g.status == "finished_black"
    assert len(g.moves) == 9  # 8 engine-ходов поверх предзаполненного центра
