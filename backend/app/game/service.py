import uuid
from collections.abc import Sequence

from app.domain.game import undo_truncate
from app.domain.opening import CENTER
from app.domain.rules import outcome_after
from app.domain.undo import UndoPolicy, check_undo
from app.domain.values import (
    Color,
    GameStatus,
    MoveRejected,
    MoveRejectReason,
    Point,
    color_of_move,
    color_to_move,
)
from app.exceptions import NotFoundError
from app.game.controllers import Engine, User, controller_from_json, controller_to_json
from app.game.players import Player, make_player
from app.game_service import apply_move
from app.models.game import Game
from app.rapfi.adapter import EngineError


class GameService:
    def __init__(self, repo, hub, adapter, levels: dict):
        self._repo = repo
        self._hub = hub
        self._adapter = adapter
        self._levels = levels  # level_id → EngineParams

    async def fouls(self, game: Game, moves: Sequence[Point]) -> list[Point]:
        """Мемо-фолы: forbidden_log[str(len)] есть → вернуть; иначе движок + запись.
        Непусто только на ход чёрных."""
        key = str(len(moves))
        log = game.forbidden_log
        if key in log:
            return [tuple(p) for p in log[key]]
        if color_to_move(len(moves)) is Color.BLACK:
            pts = await self._adapter.forbidden_points(moves)
        else:
            pts = []
        game.forbidden_log = {**log, key: [list(p) for p in pts]}  # переприсвоить (JSON-mutation)
        return list(pts)

    def _players(self, game: Game) -> dict[Color, Player]:
        return {
            Color(side): make_player(controller_from_json(c), self._adapter, self._levels)
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

    async def create_game(self, owner_id: int, opponent_level: str, human_color: str) -> Game:
        human = Color(human_color)
        engine_side = Color.WHITE if human is Color.BLACK else Color.BLACK
        controllers = {
            human.value: controller_to_json(User(owner_id)),
            engine_side.value: controller_to_json(Engine(opponent_level)),
        }
        game = Game(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            controllers=controllers,
            moves=[list(CENTER)],
            status=GameStatus.AWAITING_MOVE.value,
            undo_count=0,
            forbidden_log={},
        )
        game.status = self._next_status(game, [CENTER])  # opponent_thinking, если ход 2 за движком
        await self._repo.create(game)
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
                self._hub.publish(game.id, "status", {"status": game.status})
                await self._repo.update(game)
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
                # фолы только на ход чёрных (forbidden_points тоже может бросить EngineError)
                fb = await self.fouls(game, moves) if side is Color.BLACK else []
                game.moves = [list(p) for p in apply_move(moves, mv, forbidden=fb)]
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
        fb = await self.fouls(game, moves)  # из лога (записан advance'ом), без движка
        game.moves = [list(p) for p in apply_move(moves, point, forbidden=fb)]
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
            self._hub.publish(game.id, "status", {"status": game.status})
        await self._repo.update(game)
        return game  # advance НЕ здесь: при opponent_thinking роутер запланирует фоновый прогон

    async def undo(self, game_id: str, user_id: int) -> Game:
        game = await self._load_owned(game_id, user_id)
        check_undo(
            policy=UndoPolicy(),
            status=GameStatus(game.status),
            undo_count=game.undo_count,
        )
        my_side = next(
            s for s, c in game.controllers.items() if controller_from_json(c) == User(user_id)
        )
        new_moves = undo_truncate(moves=[tuple(m) for m in game.moves], for_color=Color(my_side))
        k = len(new_moves)
        game.moves = [list(p) for p in new_moves]
        game.forbidden_log = {key: v for key, v in game.forbidden_log.items() if int(key) <= k}
        game.undo_count += 1
        game.status = GameStatus.AWAITING_MOVE.value
        self._hub.publish(game.id, "undo", {"move_count": k})
        # из лога напрямую — undo структурно без движка (не через fouls, который
        # на отсутствующем ключе чёрной позиции дёрнул бы forbidden_points)
        fb = [tuple(p) for p in game.forbidden_log.get(str(k), [])]
        if fb:
            self._hub.publish(game.id, "forbidden", {"points": [list(p) for p in fb]})
        await self._repo.update(game)
        return game
