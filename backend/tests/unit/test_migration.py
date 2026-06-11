import subprocess

from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_users(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    cols = {c["name"] for c in inspect(eng).get_columns("users")}
    assert {"id", "username", "password_hash", "role", "token_epoch", "created_at"} <= cols
    eng.dispose()
