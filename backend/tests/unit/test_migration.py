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


def test_alembic_upgrade_creates_games(tmp_path, monkeypatch):
    import subprocess

    from sqlalchemy import create_engine, inspect

    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    insp = inspect(eng)
    assert "games" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("games")}
    assert {
        "id",
        "owner_id",
        "controllers",
        "moves",
        "status",
        "undo_count",
        "forbidden_log",
        "created_at",
        "updated_at",
    } <= cols
    fks = insp.get_foreign_keys("games")
    assert any(fk["referred_table"] == "users" for fk in fks)
    eng.dispose()


def test_alembic_upgrade_game_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    insp = inspect(eng)
    games_cols = {c["name"] for c in insp.get_columns("games")}
    assert "favorite" in games_cols
    assert "finished_at" in games_cols
    assert "user_settings" in insp.get_table_names()
    eng.dispose()
