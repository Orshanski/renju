from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{settings.resolved_db_path}")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _record):  # PRAGMA на sync_engine — иначе не подключится
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute(f"PRAGMA busy_timeout={settings.busy_timeout_ms}")
        cur.close()

    return engine
