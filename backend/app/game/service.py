import uuid
from collections.abc import Sequence

from ..domain.errors import MoveRejected, MoveRejectReason
from ..domain.game import undo_truncate
from ..domain.opening import CENTER
from ..domain.retention import Section, game_section
from ..domain.rules import outcome_after, winning_line
from ..domain.undo import UndoPolicy, check_undo
from ..domain.values import (
    Color,
    GameStatus,
    Point,
    color_of_move,
    color_to_move,
)
from ..exceptions import ConflictError, NotFoundError
from ..models.game import Game
from ..rapfi.adapter import EngineError
from ._time import _now
from .controllers import Engine, User, controller_from_json, controller_to_json, engine_nnue
from .moves import apply_move
from .players import Player, make_player
from .ports import EngineAdapter, EventHub
from .repository import GameRepository
from .retention_service import RetentionService
from .settings_repository import SettingsRepository


def _final_status_payload(game: Game) -> dict:
    """Payload финального status: статус + winning_line (ничья линии не имеет → без поля)."""
    payload: dict = {"status": game.status}
    wl = winning_line([tuple(m) for m in game.moves])
    if wl is not None:
        payload["winning_line"] = [list(p) for p in wl]
    return payload


class GameService:
    def __init__(
        self,
        repo: GameRepository,
        hub: EventHub,
        adapter: EngineAdapter,
        settings_repo: SettingsRepository,
    ):
        self._repo = repo
        self._hub = hub
        self._adapter = adapter
        self._settings_repo = settings_repo
        self._retention = RetentionService(self._repo, self._settings_repo)

    async def fouls(self, game: Game, moves: Sequence[Point]) -> list[Point]:
        """Мемо-фолы: forbidden_log[str(len)] есть → вернуть; иначе движок + запись.
        Непусто только на ход чёрных."""
        key = str(len(moves))
        log = game.forbidden_log
        if key in log:
            return [tuple(p) for p in log[key]]
        if color_to_move(len(moves)) is Color.BLACK:
            pts = await self._adapter.forbidden_points(
                game.id, moves, level_tag="-", nnue=engine_nnue(game.controllers)
            )
        else:
            pts = []
        game.forbidden_log = {**log, key: [list(p) for p in pts]}  # переприсвоить (JSON-mutation)
        return list(pts)

    def _players(self, game: Game) -> dict[Color, Player]:
        return {
            Color(side): make_player(controller_from_json(c), self._adapter, game.id)
            for side, c in game.controllers.items()
        }

    def _is_engine(self, game: Game, side: Color) -> bool:
        return isinstance(controller_from_json(game.controllers[side.value]), Engine)

    def _next_status(self, game: Game, moves: Sequence[Point]) -> str:
        """Статус ПОСЛЕ применённого хода, позиционно (без роли): завершено → finished_*;
        следующий ход за движком → opponent_thinking (request-путь вернётся сразу, движок
        сходит фоновым advance); за интерактивной стороной → awaiting_move."""
        outcome = outcome_after(moves)
        if outcome is not None:
            return outcome.value
        side = color_to_move(len(moves))
        return (
            GameStatus.OPPONENT_THINKING.value
            if self._is_engine(game, side)
            else GameStatus.AWAITING_MOVE.value
        )

    def _set_finished_at(self, game: Game) -> None:
        """Ставит finished_at при переходе в is_finished. Идемпотентно: не перезатирает
        уже выставленный момент (undo сбрасывает его в None, доигра проставит заново)."""
        if GameStatus(game.status).is_finished and game.finished_at is None:
            game.finished_at = _now()

    async def _evict_current(self, owner_id: int) -> None:
        await self._retention.evict_current(owner_id)

    async def _evict_finished(self, owner_id: int) -> None:
        await self._retention.evict_finished(owner_id)

    async def enforce_limits(self, owner_id: int) -> None:
        """Подрезает оба раздела (CURRENT + FINISHED) до лимитов.
        Вызывается из settings-update эндпоинта."""
        await self._retention.enforce_limits(owner_id)

    async def create_game(
        self,
        owner_id: int,
        engine_ctl: Engine,
        human_color: str,
    ) -> Game:
        """Создать партию. engine_ctl — замороженный снимок конфига движка
        (level_id + strength + timeout_ms + nnue)."""
        human = Color(human_color)
        engine_side = Color.WHITE if human is Color.BLACK else Color.BLACK
        controllers = {
            human.value: controller_to_json(User(owner_id)),
            engine_side.value: controller_to_json(engine_ctl),
        }
        game = Game(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            controllers=controllers,
            moves=[list(CENTER)],
            status=GameStatus.AWAITING_MOVE.value,
            undo_count=0,
            forbidden_log={},
            favorite=False,
            finished_at=None,
        )
        game.status = self._next_status(game, [CENTER])  # opponent_thinking, если ход 2 за движком
        await self._repo.create(game)
        await self._evict_current(owner_id)
        return game  # advance НЕ здесь — фоновый прогон планирует роутер (Task 10)

    async def advance(self, game: Game) -> None:
        """Единый цикл продвижения. Зовётся ТОЛЬКО из фоновой задачи роутера (своя сессия)
        или из юнит-теста. take_turn() engine-стороны (расчёт движка) крутится только здесь."""
        players = self._players(game)
        while True:
            moves = [tuple(m) for m in game.moves]
            outcome = outcome_after(moves)
            if outcome is not None:
                game.status = outcome.value
                self._set_finished_at(game)
                self._hub.publish(game.id, "status", _final_status_payload(game))
                await self._repo.update(game)
                await self._evict_finished(game.owner_id)
                return
            side = color_to_move(len(moves))
            if not self._is_engine(game, side):  # интерактивная — ждём подачу
                game.status = GameStatus.AWAITING_MOVE.value
                fb = await self.fouls(game, moves)
                if fb:
                    self._hub.publish(game.id, "forbidden", {"points": [list(p) for p in fb]})
                self._hub.publish(game.id, "status", {"status": game.status})
                await self._repo.update(game)
                return
            game.status = GameStatus.OPPONENT_THINKING.value
            self._hub.publish(game.id, "status", {"status": game.status})
            await self._repo.update(game)
            try:
                mv = await players[side].take_turn(moves)
                assert mv is not None  # engine-сторона всегда даёт ход (None только у Interactive)
                game.moves = [list(p) for p in apply_move(moves, mv)]
                game.updated_at = _now()  # реальный ход движка — бампаем «когда обновлено»
            except (EngineError, MoveRejected) as e:
                # сбой движка ИЛИ нелегальный ход движка (фол-точка) → событие error,
                # статус остаётся opponent_thinking; §4.8-восстановление доиграет при доступе
                self._hub.publish(game.id, "error", {"message": str(e)})
                return
            self._hub.publish(
                game.id,
                "move",
                {
                    "by": color_of_move(len(game.moves) - 1).value,
                    "point": list(mv),
                    "move_index": len(game.moves) - 1,
                },
            )
            await self._repo.update(game)

    async def _load_owned(self, game_id: str, user_id: int) -> Game:
        game = await self._repo.get(game_id)
        if game is None or user_id not in self._controller_user_ids(game):
            raise NotFoundError("Game not found")
        return game

    def _controller_user_ids(self, game: Game) -> set[int]:
        out: set[int] = set()
        for c in game.controllers.values():
            ctl = controller_from_json(c)
            if isinstance(ctl, User):
                out.add(ctl.user_id)
        return out

    async def submit_move(self, game_id: str, user_id: int, point: Point) -> Game:
        game = await self._load_owned(game_id, user_id)
        if game.status != GameStatus.AWAITING_MOVE.value:
            raise MoveRejected(MoveRejectReason.OPPONENT_THINKING)
        moves = [tuple(m) for m in game.moves]
        side = color_to_move(len(moves))
        ctl = controller_from_json(game.controllers[side.value])
        if not (isinstance(ctl, User) and ctl.user_id == user_id):
            raise MoveRejected(MoveRejectReason.NOT_YOUR_TURN)
        # Фолы/зону здесь НЕ сторожим: фронт не даёт человеку в фол/вне зоны, а форвард-игра
        # уже записала forbidden_log для отдачи фронту. apply_move бережёт лишь целостность.
        game.moves = [list(p) for p in apply_move(moves, point)]
        game.updated_at = _now()  # реальный ход — бампаем «когда обновлено»
        self._hub.publish(
            game.id,
            "move",
            {
                "by": color_of_move(len(game.moves) - 1).value,
                "point": list(point),
                "move_index": len(game.moves) - 1,
            },
        )
        game.status = self._next_status(game, [tuple(m) for m in game.moves])
        if GameStatus(game.status).is_finished:  # ход человека завершил партию — фона не будет
            self._set_finished_at(game)
            self._hub.publish(game.id, "status", _final_status_payload(game))
            await self._repo.update(game)
            await self._evict_finished(game.owner_id)
        else:
            await self._repo.update(game)
        return game  # advance НЕ здесь: при opponent_thinking роутер запланирует фоновый прогон

    async def get_game(self, game_id: str, user_id: int) -> Game:
        # чистый доступ с проверкой участия; восстановление (фоновый advance при
        # opponent_thinking) планирует роутер — сервис не владеет фоновыми сессиями.
        return await self._load_owned(game_id, user_id)

    async def load(self, game_id: str) -> Game | None:
        # сырая загрузка по id (без проверки участия) — для фоновой задачи роутера,
        # которая прогоняет advance уже после того, как запрос проверил доступ.
        return await self._repo.get(game_id)

    async def list_games(self, owner_id: int) -> list[Game]:
        return await self._repo.list_by_owner(owner_id)

    async def undo(self, game_id: str, user_id: int) -> Game:
        game = await self._load_owned(game_id, user_id)
        settings = await self._settings_repo.get_or_default(user_id)
        policy = UndoPolicy(
            enabled=settings.undo_enabled,
            limit=settings.undo_limit,
            after_game_end=settings.undo_after_game_end,
        )
        check_undo(
            policy=policy,
            status=GameStatus(game.status),
            undo_count=game.undo_count,
        )
        my_side = next(
            s for s, c in game.controllers.items() if controller_from_json(c) == User(user_id)
        )
        new_moves = undo_truncate(moves=[tuple(m) for m in game.moves], for_color=Color(my_side))
        k = len(new_moves)
        await self._adapter.sync_after_undo(game.id, new_moves)
        game.moves = [list(p) for p in new_moves]
        game.forbidden_log = {key: v for key, v in game.forbidden_log.items() if int(key) <= k}
        game.undo_count += 1
        game.status = GameStatus.AWAITING_MOVE.value
        game.finished_at = None
        game.updated_at = _now()  # усечение ходов — реальное изменение партии
        self._hub.publish(game.id, "undo", {"move_count": k})
        # из лога напрямую — undo структурно без движка (не через fouls, который
        # на отсутствующем ключе чёрной позиции дёрнул бы forbidden_points)
        fb = [tuple(p) for p in game.forbidden_log.get(str(k), [])]
        if fb:
            self._hub.publish(game.id, "forbidden", {"points": [list(p) for p in fb]})
        await self._repo.update(game)
        return game

    async def favorite_game(self, game_id: str, user_id: int) -> Game:
        """Помечает завершённую партию как избранную. На незавершённой → ConflictError."""
        game = await self._load_owned(game_id, user_id)
        if game_section(game.status, bool(game.favorite)) is not Section.FINISHED:
            raise ConflictError("Only finished (non-favorite) games can be marked as favorite")
        game.favorite = True
        await self._repo.update(game)
        return game

    async def unfavorite_game(self, game_id: str, user_id: int) -> Game:
        """Снимает отметку избранного. finished_at НЕ трогаем; проверяет лимит."""
        game = await self._load_owned(game_id, user_id)
        game.favorite = False
        await self._repo.update(game)
        await self._evict_finished(game.owner_id)
        return game

    async def delete_game(self, game_id: str, user_id: int) -> None:
        """Удаляет партию. Чужому/несуществующей → NotFoundError."""
        await self._load_owned(game_id, user_id)
        await self._repo.delete(game_id)

    async def bulk_delete(self, user_id: int, section: Section) -> int:
        """Удалить все партии пользователя в указанном разделе (current или finished)."""
        games = await self._repo.list_by_owner(user_id)
        ids = [g.id for g in games if game_section(g.status, g.favorite) is section]
        for game_id in ids:
            await self._repo.delete(game_id)
        return len(ids)
