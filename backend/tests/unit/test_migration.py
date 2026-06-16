import json
import subprocess

from sqlalchemy import create_engine, inspect, text


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


def test_backfill_frozen_engine_config(tmp_path, monkeypatch):
    """engine_config-миграция дописывает strength/timeout_ms/nnue в engine-контроллеры."""
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))

    # 1. Поднимаем схему до ревизии ПЕРЕД engine_config
    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "eab503b3e51b"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr

    # 2. Вставляем тестовые данные: юзер + партия со старым Engine-контроллером (без frozen-полей)
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    old_ctl = {
        "black": {"kind": "user", "user_id": 1},
        "white": {"kind": "engine", "level_id": "master"},  # без strength/timeout_ms/nnue
    }
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, token_epoch) "
                "VALUES (1, 'alice', 'x', 'user', 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO games (id, owner_id, controllers, moves, status, undo_count, "
                "forbidden_log, favorite, finished_at) VALUES "
                "('g1', 1, :ctl, '[[7,7]]', 'awaiting_move', 0, '{}', 0, NULL)"
            ),
            {"ctl": json.dumps(old_ctl)},
        )
    eng.dispose()

    # 3. Накатываем миграцию engine_config
    r2 = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    assert r2.returncode == 0, r2.stderr

    # 4. Проверяем, что у engine-стороны появились frozen-поля
    eng2 = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng2.connect() as conn:
        row = conn.execute(text("SELECT controllers FROM games WHERE id='g1'")).fetchone()
    eng2.dispose()

    assert row is not None
    ctl_after = json.loads(row[0])
    white_ctl = ctl_after["white"]
    assert white_ctl["kind"] == "engine"
    assert white_ctl["level_id"] == "master"
    assert white_ctl["strength"] == 90
    assert white_ctl["timeout_ms"] == 6000
    assert white_ctl["nnue"] is True


def test_backfill_skips_placeholder_level(tmp_path, monkeypatch):
    """engine_config-миграция НЕ падает на engine с level_id='-'."""
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))

    r = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "eab503b3e51b"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr

    placeholder_ctl = {
        "black": {"kind": "user", "user_id": 1},
        "white": {"kind": "engine", "level_id": "-"},
    }
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, token_epoch) "
                "VALUES (1, 'alice', 'x', 'user', 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO games (id, owner_id, controllers, moves, status, undo_count, "
                "forbidden_log, favorite, finished_at) VALUES "
                "('g2', 1, :ctl, '[[7,7]]', 'awaiting_move', 0, '{}', 0, NULL)"
            ),
            {"ctl": json.dumps(placeholder_ctl)},
        )
    eng.dispose()

    r2 = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    assert r2.returncode == 0, r2.stderr  # не упало

    eng2 = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng2.connect() as conn:
        row = conn.execute(text("SELECT controllers FROM games WHERE id='g2'")).fetchone()
    eng2.dispose()

    ctl_after = json.loads(row[0])
    white_ctl = ctl_after["white"]
    # Плейсхолдер не трогаем — frozen-полей нет
    assert "strength" not in white_ctl
    assert "nnue" not in white_ctl
