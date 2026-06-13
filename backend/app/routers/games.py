import asyncio
import json as _json
import logging
import random
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, decode_token, fetch_token_epoch, get_current_user
from ..db.deps import get_session
from ..domain.retention import game_section
from ..domain.rules import winning_line
from ..domain.values import GameStatus, MoveRejected, UndoRejected
from ..exceptions import BadInputError
from ..game.dtos import CreateGameBody, GameSummaryDTO, LevelDTO
from ..game.repository import SqlGameRepository
from ..game.service import GameService
from ..game.settings_repository import SqlSettingsRepository
from ..levels_config import resolve_level
from ..logging_utils import safe
from .auth import current_user

logger = logging.getLogger("renju.games")
router = APIRouter(prefix="/api", tags=["games"])


def _build_service(app: FastAPI, session: AsyncSession) -> GameService:
    levels = {lid: lv.params for lid, lv in app.state.levels.items()}
    return GameService(
        repo=SqlGameRepository(session),
        hub=app.state.event_hub,
        adapter=app.state.adapter,
        levels=levels,
        settings_repo=SqlSettingsRepository(session),
    )


def _service(request: Request, session: AsyncSession) -> GameService:
    return _build_service(request.app, session)


def schedule_advance(app: FastAPI, game_id: str) -> None:
    """Фоновый прогон engine-ходов: СВОЯ сессия (request-сессия уже закрыта), свой
    GameService. Движок крутится только в advance, а advance — только здесь и в юнит-тестах.
    Дедуп по game_id (app.state.advancing): уже крутится → не плодим дубль. Идемпотентно (Task 9).
    Только ПЛАНИРУЕТ задачу (`create_task` не исполняет тело синхронно): между этим вызовом
    и последующим `_state`/`cursor` нет `await`, поэтому cursor снимается ДО первого хода
    advance (спека §4.6: реплей с этого cursor догонит события advance)."""
    if app.state.adapter is None:  # E1: движок не собран — фон бессмыслен
        logger.warning(
            "schedule_advance: adapter=None, game=%s остаётся opponent_thinking", game_id
        )
        return
    if game_id in app.state.advancing:  # уже есть активный фоновый advance на эту партию
        return
    app.state.advancing.add(game_id)

    async def _run() -> None:
        try:
            async with app.state.sessionmaker() as s:
                svc = _build_service(app, s)
                game = await svc.load(game_id)
                if game is not None:
                    await svc.advance(game)
        except Exception:
            logger.exception("background advance failed: game=%s", game_id)
        finally:
            app.state.advancing.discard(game_id)

    task = asyncio.create_task(_run())
    app.state.bg_tasks.add(task)
    task.add_done_callback(app.state.bg_tasks.discard)


def _public_controllers(controllers: dict) -> dict:  # id чужого игрока не светим
    return {
        side: (
            {"kind": "engine", "levelId": c["level_id"]}
            if c["kind"] == "engine"
            else {"kind": "user"}
        )
        for side, c in controllers.items()
    }


def _your_color(controllers: dict, user_id: int) -> str | None:
    for side, c in controllers.items():
        if c["kind"] == "user" and c["user_id"] == user_id:
            return side
    return None


def _engine_level_id(controllers: dict) -> str | None:
    """level_id engine-оппонента для summary; None если engine-стороны нет (или '-' нет смысла)."""
    for c in controllers.values():
        if c.get("kind") == "engine":
            lid = c.get("level_id", "-")
            return lid if lid != "-" else None
    return None


def _loaded(game, attr: str):
    """Значение атрибута БЕЗ неявного async-lazy-load: server-onupdate колонка
    (updated_at) после commit помечена expired, а её чтение в sync-проперти дёрнуло бы
    DB-round-trip (MissingGreenlet). На горячем пути refresh нам не нужен — для summary
    хватит того, что уже в identity map; expired → None (значение косметическое)."""
    from sqlalchemy import inspect as _inspect

    state = _inspect(game)
    return getattr(game, attr) if attr not in state.unloaded else None


def _summary(game, user_id: int) -> GameSummaryDTO:
    return GameSummaryDTO(
        id=game.id,
        status=game.status,
        section=game_section(game.status, game.favorite).value,
        level_id=_engine_level_id(game.controllers),
        your_color=_your_color(game.controllers, user_id),
        move_count=len(game.moves),
        favorite=game.favorite,
        updated_at=_loaded(game, "updated_at"),
        finished_at=game.finished_at,
    )


def _state(game, user_id: int, hub) -> dict:
    fb = game.forbidden_log.get(str(len(game.moves)), [])
    wl = (
        winning_line([tuple(m) for m in game.moves])
        if GameStatus(game.status).is_finished
        else None
    )
    return {
        "id": game.id,
        "owner_id": game.owner_id,
        "controllers": _public_controllers(game.controllers),
        "your_color": _your_color(game.controllers, user_id),
        "status": game.status,
        "moves": game.moves,
        "undo_count": game.undo_count,
        "cursor": hub.cursor(game.id),
        "forbidden": fb,
        "winning_line": [list(p) for p in wl] if wl is not None else None,
    }


@router.get("/levels", response_model=list[LevelDTO])
async def levels(request: Request, _: Annotated[CurrentUser, Depends(current_user)]):
    return [LevelDTO(id=lv.id, name=lv.name) for lv in request.app.state.levels.values()]


@router.post("/games")
async def create_game(
    body: CreateGameBody,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if body.opponent.kind != "engine":
        raise BadInputError("only engine opponent supported")
    if resolve_level(list(request.app.state.levels.values()), body.opponent.levelId) is None:
        raise BadInputError("unknown levelId")
    svc = _service(request, session)
    human = random.choice(["black", "white"])
    game = await svc.create_game(
        owner_id=user.user_id, opponent_level=body.opponent.levelId, human_color=human
    )
    if game.status == GameStatus.OPPONENT_THINKING.value:  # человек-чёрный → движок в фоне
        schedule_advance(request.app, game.id)
    return _state(game, user.user_id, request.app.state.event_hub)


@router.get("/games")
async def list_games(
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    hub = request.app.state.event_hub
    return [
        _state(g, user.user_id, hub)
        for g in await _service(request, session).list_games(user.user_id)
    ]


@router.get("/games/summary", response_model=list[GameSummaryDTO])
async def list_games_summary(
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    games = await _service(request, session).list_games(user.user_id)
    return [_summary(g, user.user_id) for g in games]


@router.delete("/games/{game_id}", status_code=204)
async def delete_game(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await _service(request, session).delete_game(game_id, user.user_id)


@router.post("/games/{game_id}/favorite")
async def favorite_game(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    game = await _service(request, session).favorite_game(game_id, user.user_id)
    return _summary(game, user.user_id)


@router.post("/games/{game_id}/unfavorite")
async def unfavorite_game(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    game = await _service(request, session).unfavorite_game(game_id, user.user_id)
    return _summary(game, user.user_id)


@router.get("/games/{game_id}")
async def get_game(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    game = await _service(request, session).get_game(game_id, user.user_id)
    if game.status == GameStatus.OPPONENT_THINKING.value:  # §4.8: застрявшая → доиграть фоном
        schedule_advance(request.app, game_id)
    return _state(game, user.user_id, request.app.state.event_hub)


class MoveBody(BaseModel):
    x: int
    y: int


@router.post("/games/{game_id}/move", status_code=202)
async def move(
    game_id: str,
    body: MoveBody,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        game = await _service(request, session).submit_move(game_id, user.user_id, (body.x, body.y))
    except MoveRejected as e:
        logger.warning(
            "move rejected: game=%s user=%s point=%s reason=%s",
            safe(game_id),
            user.user_id,
            safe((body.x, body.y)),
            safe(e.reason.value),
        )
        raise
    if game.status == GameStatus.OPPONENT_THINKING.value:  # ход соперника-движка — в фоне
        schedule_advance(request.app, game_id)
    return {"accepted": True}  # 202: ход принят; ответ соперника придёт SSE-событием


@router.post("/games/{game_id}/undo")
async def undo(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        game = await _service(request, session).undo(game_id, user.user_id)
    except UndoRejected as e:
        logger.warning(
            "undo rejected: game=%s user=%s reason=%s",
            safe(game_id),
            user.user_id,
            safe(e.reason.value),
        )
        raise
    return _state(game, user.user_id, request.app.state.event_hub)


def _engine_level_tag(controllers: dict) -> str:
    """level_id engine-оппонента (для логов реестра); '-' если engine-стороны нет."""
    for c in controllers.values():
        if c.get("kind") == "engine":
            return c["level_id"]
    return "-"


@router.post("/games/{game_id}/enter")
async def enter(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    # presence++ (поднимает/переиспользует процесс партии). Вход с экрана /game/:id.
    game = await _service(request, session).get_game(game_id, user.user_id)  # 404 если нет доступа
    adapter = request.app.state.adapter
    if adapter is not None:
        await adapter.mark_present(game_id, _engine_level_tag(game.controllers))
    return {"ok": True}


@router.post("/games/{game_id}/leave")
async def leave(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    # presence-- (гасит процесс, если ушло последнее устройство и нет идущего расчёта).
    await _service(request, session).get_game(game_id, user.user_id)  # 404 если нет доступа
    adapter = request.app.state.adapter
    if adapter is not None:
        await adapter.mark_absent(game_id)
    return {"ok": True}


@router.get("/games/{game_id}/events")
async def events(game_id: str, request: Request, since: int = 0):
    # SSE — долгоживущий стрим: НЕ берём Depends(current_user)/Depends(get_session)
    # (они держали бы request-сессию открытой весь стрим). Auth+доступ — на КОРОТКОЙ сессии.
    hub = request.app.state.event_hub
    sm = request.app.state.sessionmaker
    settings = request.app.state.settings
    async with sm() as s0:
        user = await get_current_user(request, s0, settings)  # нет cookie/отозван → AuthError→401
        game = await _service(request, s0).get_game(game_id, user.user_id)  # 404 если нет доступа
    if game.status == GameStatus.OPPONENT_THINKING.value:  # §4.8: застрявшая → доиграть фоном
        schedule_advance(request.app, game_id)
    jwt_epoch = decode_token(request.cookies[settings.cookie_name], settings).get("tep", 0)

    async def gen():
        # heartbeat живёт ВНУТРИ subscribe (idle_timeout) — НЕ оборачиваем __anext__ снаружи (B-2)
        async for ev in hub.subscribe(game_id, since, idle_timeout=settings.sse_heartbeat_s):
            if ev["type"] == "ping":
                async with sm() as s2:  # epoch-recheck на свежей короткой сессии
                    cur = await fetch_token_epoch(s2, user.user_id)
                if cur is None or cur != jwt_epoch:
                    return  # сессия отозвана — закрыть стрим
                yield ": ping\n\n"
            else:  # data = весь объект события {seq, type, payload} (спека §«Контракт SSE», N-2)
                yield f"event: {ev['type']}\ndata: {_json.dumps(ev)}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )
