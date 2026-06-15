from ..domain.retention import game_section
from ..domain.rules import winning_line
from ..domain.values import GameStatus
from .controllers import engine_level_id, public_view, user_side
from .dtos import GameSummaryDTO


def summary_dto(game, user_id: int) -> GameSummaryDTO:
    return GameSummaryDTO(
        id=game.id,
        status=game.status,
        section=game_section(game.status, game.favorite).value,
        level_id=engine_level_id(game.controllers),
        your_color=user_side(game.controllers, user_id),
        move_count=len(game.moves),
        # мини-доска карточки (rj-6ub); уже загружено для move_count. Без пагинации: список
        # завершённых растёт со временем, а на партию приедет весь moves (≤225 точек). Осознанно
        # ОК для self-hosted/свои (нет PvP, строки партий и так грузятся целиком); если раздел
        # станет большим — пагинировать сводку или тянуть миниатюру лениво.
        moves=game.moves,
        favorite=game.favorite,
        updated_at=game.updated_at,
        finished_at=game.finished_at,
    )


def state_payload(game, user_id: int, hub) -> dict:
    fb = game.forbidden_log.get(str(len(game.moves)), [])
    wl = (
        winning_line([tuple(m) for m in game.moves])
        if GameStatus(game.status).is_finished
        else None
    )
    return {
        "id": game.id,
        "owner_id": game.owner_id,
        "controllers": public_view(game.controllers),
        "your_color": user_side(game.controllers, user_id),
        "status": game.status,
        "moves": game.moves,
        "undo_count": game.undo_count,
        "cursor": hub.cursor(game.id),
        "forbidden": fb,
        "winning_line": [list(p) for p in wl] if wl is not None else None,
    }
