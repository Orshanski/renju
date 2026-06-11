import pytest

from app.auth import (
    AuthError,
    CurrentUser,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.config import Settings


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))  # секрет в tmp, не в репо
    return Settings()


def test_password_roundtrip():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)


def test_token_roundtrip(cfg):
    t = create_token(user_id=7, role="admin", token_epoch=3, settings=cfg)
    p = decode_token(t, cfg)
    assert p["userId"] == 7 and p["role"] == "admin" and p["tep"] == 3
    assert isinstance(p["iat"], (int, float))  # PyJWT декодирует iat как unix-timestamp


def test_decode_tampered_raises(cfg):
    with pytest.raises(Exception):  # noqa: B017  — любой jwt-error достаточен здесь
        decode_token("not.a.jwt", cfg)


def test_current_user_from_payload_ok():
    u = CurrentUser.from_payload({"userId": 7, "role": "admin"})
    assert u.user_id == 7 and u.role == "admin"


@pytest.mark.parametrize(
    "bad",
    [{"role": "user"}, {"userId": True, "role": "u"}, {"userId": 1}, {"userId": 1, "role": ""}],
)
def test_current_user_from_payload_rejects(bad):
    with pytest.raises(AuthError):
        CurrentUser.from_payload(bad)


def test_token_needs_refresh_unix_iat(cfg):
    from datetime import UTC, datetime, timedelta

    from app.auth import token_needs_refresh

    old = (datetime.now(UTC) - timedelta(hours=200)).timestamp()  # unix-timestamp!
    assert token_needs_refresh({"iat": old}, cfg) is True
    fresh = datetime.now(UTC).timestamp()
    assert token_needs_refresh({"iat": fresh}, cfg) is False
