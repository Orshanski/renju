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
