from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth import AuthError
from app.exceptions import (
    BadInputError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
)

_MAP = [
    (BadInputError, 400),
    (NotFoundError, 404),
    (ConflictError, 409),
    (ForbiddenError, 403),
    (AuthError, 401),
    (RateLimitError, 429),
]


def register_error_handlers(app: FastAPI) -> None:
    for exc_type, status in _MAP:

        def make(status_code):
            def handler(_request: Request, exc: Exception) -> JSONResponse:
                return JSONResponse(status_code=status_code, content={"detail": str(exc)})

            return handler

        app.add_exception_handler(exc_type, make(status))

    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        import logging

        logging.getLogger("renju").exception("Unhandled: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    # 500 без утечки причины (спека §Обработка ошибок)
    app.add_exception_handler(Exception, _unhandled)
