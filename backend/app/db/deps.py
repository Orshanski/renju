from fastapi import Request

from app.config import Settings
from app.db.session import session_scope


async def get_session(request: Request):
    sm = request.app.state.sessionmaker
    async for s in session_scope(sm):
        yield s


def get_settings(request: Request) -> Settings:
    return request.app.state.settings
