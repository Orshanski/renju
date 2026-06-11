from fastapi.responses import JSONResponse

_SAFE = {"GET", "HEAD", "OPTIONS"}


def add_csrf_guard(app):
    @app.middleware("http")
    async def _mw(request, call_next):
        if request.url.path.startswith("/api/") and request.method not in _SAFE:
            if request.headers.get("X-Requested-With") != "XMLHttpRequest":
                return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
        return await call_next(request)
