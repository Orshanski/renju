from collections.abc import Sequence

from app.domain.values import Color, Point, color_to_move
from app.models.game import Game


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
