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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        yield
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

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    return app
