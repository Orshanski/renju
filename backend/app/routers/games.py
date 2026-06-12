import asyncio
import logging
import random
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db.deps import get_session
from app.domain.values import GameStatus
from app.exceptions import BadInputError
from app.game.dtos import CreateGameBody, LevelDTO
from app.game.repository import SqlGameRepository
from app.game.service import GameService
from app.levels_config import resolve_level
from app.routers.auth import current_user

logger = logging.getLogger("renju.games")
router = APIRouter(prefix="/api", tags=["games"])


def _build_service(app: FastAPI, session: AsyncSession) -> GameService:
    levels = {lid: lv.params for lid, lv in app.state.levels.items()}
    return GameService(
        repo=SqlGameRepository(session),
        hub=app.state.event_hub,
        adapter=app.state.adapter,
        levels=levels,
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


def _state(game, user_id: int, hub) -> dict:
    fb = game.forbidden_log.get(str(len(game.moves)), [])
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
