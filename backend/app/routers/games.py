import json as _json
import logging
import random
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, decode_token, fetch_token_epoch, get_current_user
from ..config_repository import ConfigRepository
from ..db.deps import get_session
from ..domain.errors import MoveRejected, UndoRejected
from ..domain.retention import Section, game_section
from ..domain.values import GameStatus
from ..exceptions import BadInputError
from ..game.controllers import Engine, engine_level_tag
from ..game.deps import build_game_service, make_game_service
from ..game.dtos import CreateGameBody, GameSummaryDTO, LevelDTO
from ..game.mappers import state_payload, summary_dto
from ..game.service import GameService
from ..logging_utils import safe
from .auth import current_user

logger = logging.getLogger("renju.games")
router = APIRouter(prefix="/api", tags=["games"])


@router.get("/levels", response_model=list[LevelDTO])
async def levels(
    _: Annotated[CurrentUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    cfg = ConfigRepository(session)
    return [LevelDTO(id=lv.id, name=lv.name) for lv in await cfg.levels()]


@router.post("/games")
async def create_game(
    body: CreateGameBody,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if body.opponent.kind != "engine":
        raise BadInputError("only engine opponent supported")
    cfg = ConfigRepository(session)
    level = await cfg.get_level(body.opponent.levelId)
    if level is None:
        raise BadInputError("unknown levelId")
    nnue = await cfg.nnue()
    engine_ctl = Engine(
        level_id=level.id,
        strength=level.strength,
        timeout_ms=level.timeout_ms,
        nnue=nnue,
    )
    human = random.choice(["black", "white"])
    game = await service.create_game(
        owner_id=user.user_id, engine_ctl=engine_ctl, human_color=human
    )
    if game.status == GameStatus.OPPONENT_THINKING.value:  # человек-чёрный → движок в фоне
        request.app.state.advance.schedule(game.id)
    return state_payload(game, user.user_id, request.app.state.event_hub)


@router.get("/games")
async def list_games(
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    hub = request.app.state.event_hub
    return [state_payload(g, user.user_id, hub) for g in await service.list_games(user.user_id)]


@router.get("/games/summary", response_model=list[GameSummaryDTO])
async def list_games_summary(
    section: Section,  # обязательный фильтр (current|finished|favorite); невалидное → 422
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    games = await service.list_games(user.user_id)
    return [
        summary_dto(g, user.user_id) for g in games if game_section(g.status, g.favorite) is section
    ]


@router.delete("/games/{game_id}", status_code=204)
async def delete_game(
    game_id: str,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    await service.delete_game(game_id, user.user_id)


@router.post("/games/{game_id}/favorite")
async def favorite_game(
    game_id: str,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    await service.favorite_game(game_id, user.user_id)
    return True


@router.post("/games/{game_id}/unfavorite")
async def unfavorite_game(
    game_id: str,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    await service.unfavorite_game(game_id, user.user_id)
    return True


@router.get("/games/{game_id}")
async def get_game(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    game = await service.get_game(game_id, user.user_id)
    if game.status == GameStatus.OPPONENT_THINKING.value:  # §4.8: застрявшая → доиграть фоном
        request.app.state.advance.schedule(game_id)
    return state_payload(game, user.user_id, request.app.state.event_hub)


class MoveBody(BaseModel):
    x: int
    y: int


@router.post("/games/{game_id}/move", status_code=202)
async def move(
    game_id: str,
    body: MoveBody,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    try:
        game = await service.submit_move(game_id, user.user_id, (body.x, body.y))
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
        request.app.state.advance.schedule(game_id)
    return {"accepted": True}  # 202: ход принят; ответ соперника придёт SSE-событием


@router.post("/games/{game_id}/undo")
async def undo(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    try:
        game = await service.undo(game_id, user.user_id)
    except UndoRejected as e:
        logger.warning(
            "undo rejected: game=%s user=%s reason=%s",
            safe(game_id),
            user.user_id,
            safe(e.reason.value),
        )
        raise
    return state_payload(game, user.user_id, request.app.state.event_hub)


@router.post("/games/{game_id}/enter")
async def enter(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    # presence++ (поднимает/переиспользует процесс партии). Вход с экрана /game/:id.
    game = await service.get_game(game_id, user.user_id)  # 404 если нет доступа
    adapter = request.app.state.adapter
    if adapter is not None:
        await adapter.mark_present(game_id, engine_level_tag(game.controllers))
    return {"ok": True}


@router.post("/games/{game_id}/leave")
async def leave(
    game_id: str,
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    service: Annotated[GameService, Depends(build_game_service)],
):
    # presence-- (гасит процесс, если ушло последнее устройство и нет идущего расчёта).
    await service.get_game(game_id, user.user_id)  # 404 если нет доступа
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
        svc0 = make_game_service(request.app, s0)
        game = await svc0.get_game(game_id, user.user_id)  # 404 если нет доступа
    if game.status == GameStatus.OPPONENT_THINKING.value:  # §4.8: застрявшая → доиграть фоном
        request.app.state.advance.schedule(game_id)
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
