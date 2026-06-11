async def test_security_headers(client):
    r = await client.get("/api/health")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


async def test_csrf_blocks_post_without_header(client):
    r = await client.post(
        "/api/auth/login",
        json={"username": "x", "password": "y"},
        headers={"X-Requested-With": ""},
    )
    assert r.status_code == 403
    # security_headers — внешний слой: даже CSRF-403-short-circuit несёт заголовки
    assert r.headers["X-Frame-Options"] == "DENY"
