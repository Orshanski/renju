from app.auth import create_token


def add_refresh(app):
    @app.middleware("http")
    async def _mw(request, call_next):
        resp = await call_next(request)
        s = request.app.state.settings
        r = getattr(request.state, "refresh", None)
        if r and {"user_id", "role", "epoch"} <= r.keys() and 200 <= resp.status_code < 400:
            token = create_token(r["user_id"], r["role"], r["epoch"], s)
            resp.set_cookie(
                s.cookie_name,
                token,
                httponly=True,
                samesite="lax",
                secure=s.secure_cookie,
                max_age=s.jwt_expire_hours * 3600,
                path="/",
            )
        return resp
