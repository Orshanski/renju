from dataclasses import dataclass


@dataclass(frozen=True)
class Engine:
    level_id: str


@dataclass(frozen=True)
class User:
    user_id: int


Controller = Engine | User


def controller_to_json(c: Controller) -> dict:
    if isinstance(c, Engine):
        return {"kind": "engine", "level_id": c.level_id}
    return {"kind": "user", "user_id": c.user_id}


def controller_from_json(d: dict) -> Controller:
    return Engine(d["level_id"]) if d["kind"] == "engine" else User(d["user_id"])


def _engines(controllers: dict) -> list[Engine]:
    out: list[Engine] = []
    for c in controllers.values():
        ctl = controller_from_json(c)
        if isinstance(ctl, Engine):
            out.append(ctl)
    return out


def engine_level_id(controllers: dict) -> str | None:
    """level_id engine-оппонента; None если engine-стороны нет или это плейсхолдер '-'."""
    for eng in _engines(controllers):
        return eng.level_id if eng.level_id != "-" else None
    return None


def engine_level_tag(controllers: dict) -> str:
    """level_id engine-оппонента для логов реестра; '-' если engine-стороны нет."""
    for eng in _engines(controllers):
        return eng.level_id
    return "-"


def user_side(controllers: dict, user_id: int) -> str | None:
    """Сторона ('black'/'white'), которой управляет данный пользователь; None если его нет."""
    for side, c in controllers.items():
        ctl = controller_from_json(c)
        if isinstance(ctl, User) and ctl.user_id == user_id:
            return side
    return None


def public_view(controllers: dict) -> dict:
    """Публичная форма для фронта: id чужого игрока не светим, у движка отдаём levelId."""
    out: dict = {}
    for side, c in controllers.items():
        ctl = controller_from_json(c)
        out[side] = (
            {"kind": "engine", "levelId": ctl.level_id}
            if isinstance(ctl, Engine)
            else {"kind": "user"}
        )
    return out
