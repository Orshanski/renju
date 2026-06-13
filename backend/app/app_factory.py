import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings
from .db.engine import make_engine
from .db.session import make_sessionmaker
from .error_handlers import register_error_handlers
from .middleware.csrf import add_csrf_guard
from .middleware.refresh import add_refresh
from .middleware.security_headers import add_security_headers
from .routers import admin as admin_router
from .routers import auth as auth_router
from .routers import games as games_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from .config import REPO_ROOT
        from .game.event_hub import InMemoryEventHub
        from .levels_config import load_levels
        from .rapfi.adapter import RapfiAdapter

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
            logging.getLogger("renju").warning("Rapfi bin не собран — adapter=None")
            app.state.adapter = None
        app.state.event_hub = InMemoryEventHub()
        app.state.levels = {lv.id: lv for lv in load_levels(settings.levels_file)}  # id → LevelInfo
        app.state.bg_tasks = set()  # ссылки на фоновые advance-задачи (иначе GC оборвёт)
        app.state.advancing = set()  # game_id с активным фоновым advance (per-process дедуп)
        yield
        bg = list(app.state.bg_tasks)  # снимок: done-callback мутирует set по мере завершения
        for t in bg:  # погасить незавершённые фоновые advance И дождаться отмены до dispose
            t.cancel()
        if bg:
            await asyncio.gather(*bg, return_exceptions=True)
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

    # SPA: статика + fallback на index.html — ПОСЛЕДними, чтобы не перехватывать /api/*.
    # /api/* мимо роутера отдаёт 404 JSON (см. ниже), не index.html.
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    dist = settings.frontend_dist
    if dist.is_dir():
        dist_root = dist.resolve()
        assets = dist / "assets"
        if assets.is_dir():  # StaticFiles падает без каталога; гард — частичный dist не ронял старт
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (dist / full_path).resolve()
            # is_relative_to: ../-обход не должен выйти за dist (path-traversal). /assets-mount
            # StaticFiles защищает сам; этот корневой file-branch (favicon и пр.) — нет, гард тут.
            if full_path and candidate.is_file() and candidate.is_relative_to(dist_root):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
