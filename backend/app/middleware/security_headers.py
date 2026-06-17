_HEADERS = {
    "Content-Security-Policy": (
        # CF Web Analytics инжектит beacon.min.js со static.cloudflareinsights.com
        "default-src 'self'; script-src 'self' https://static.cloudflareinsights.com; "
        "object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; connect-src 'self'; "
        # шрифты прототипа — с Google Fonts (решение Alexey 2026-06-12); только эти два хоста
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def add_security_headers(app):
    @app.middleware("http")
    async def _mw(request, call_next):
        resp = await call_next(request)
        for k, v in _HEADERS.items():
            resp.headers.setdefault(k, v)
        if request.app.state.settings.secure_cookie:  # HSTS только на проде (Secure)
            resp.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return resp
