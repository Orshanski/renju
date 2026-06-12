from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db.engine import make_engine
from app.db.session import make_sessionmaker
from app.error_handlers import register_error_handlers
from app.middleware.csrf import add_csrf_guard
from app.middleware.refresh import add_refresh
from app.middleware.security_headers import add_security_headers
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import games as games_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.config import REPO_ROOT
        from app.game.event_hub import InMemoryEventHub
        from app.levels_config import load_levels
        from app.rapfi.adapter import RapfiAdapter

        engine = make_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        try:  # E1: НЕ сцеплять старт приложения с собранным бинарём (API-тесты подменят фейком)
            app.state.adapter = RapfiAdapter(  # как scripts/play_cli.py:62 — cwd=REPO_ROOT
                bin_path=settings.resolved_rapfi_bin(),
                config_path=settings.rapfi_config,
                cwd=REPO_ROOT,
                kill_grace_s=settings.engine_kill_grace_s,
            )
        except FileNotFoundError:
            import logging

            logging.getLogger("renju").warning("Rapfi bin не собран — adapter=None")
            app.state.adapter = None
        app.state.event_hub = InMemoryEventHub()
        app.state.levels = {lv.id: lv for lv in load_levels(settings.levels_file)}  # id → LevelInfo
        app.state.bg_tasks = set()  # ссылки на фоновые advance-задачи (иначе GC оборвёт)
        app.state.advancing = set()  # game_id с активным фоновым advance (per-process дедуп)
        yield
        for t in list(app.state.bg_tasks):  # погасить незавершённые фоновые advance
            t.cancel()
        if app.state.adapter is not None:
            await app.state.adapter.close()
        await engine.dispose()

    app = FastAPI(title="Renju", lifespan=lifespan)
    app.state.settings = settings  # доступно мидлварам/зависимостям на request-time
    register_error_handlers(app)
    # Starlette: ПОСЛЕДНИЙ зарегистрированный @middleware = ВНЕШНИЙ слой.
    # refresh — внутренний (у роутов); csrf — в середине; security_headers последним =
    # outermost — штампует заголовки на ЛЮБОЙ ответ, включая CSRF-403-short-circuit.
    add_refresh(app)
    add_csrf_guard(app)
    add_security_headers(app)
    app.include_router(auth_router.router)
    app.include_router(admin_router.router)
    app.include_router(games_router.router)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app
