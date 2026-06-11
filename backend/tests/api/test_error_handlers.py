import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth import AuthError
from app.error_handlers import register_error_handlers
from app.exceptions import (
    BadInputError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
)


@pytest.mark.parametrize(
    "exc,code",
    [
        (BadInputError, 400),
        (NotFoundError, 404),
        (ConflictError, 409),
        (ForbiddenError, 403),
        (AuthError, 401),
        (RateLimitError, 429),
    ],
)
async def test_exception_maps_to_status(exc, code):
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise exc("x")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == code and r.json() == {"detail": "x"}


async def test_unhandled_is_500_no_leak():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret-internal-detail")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        r = await c.get("/boom")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}
