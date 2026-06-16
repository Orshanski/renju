"""Настройки приложения (pydantic-settings, env-префикс RENJU_)."""

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RENJU_", env_file=".env", extra="ignore")

    rapfi_bin: Path | None = None  # RENJU_RAPFI_BIN
    rapfi_config: Path = REPO_ROOT / "engine" / "config.toml"  # RENJU_RAPFI_CONFIG
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"  # RENJU_FRONTEND_DIST
    engine_kill_grace_s: float = 2.0  # сколько ждать terminate перед kill

    data_dir: Path = REPO_ROOT / "data"  # RENJU_DATA_DIR; в тестах переопределяется
    db_path: Path | None = None  # дефолт data_dir/db.sqlite (см. resolved_db_path)
    secret_key: str | None = None  # RENJU_SECRET_KEY; иначе генерится в data_dir/.secret_key
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 168  # 7 дней
    jwt_refresh_after_hours: int = 84  # половина TTL
    cookie_name: str = "renju_token"
    secure_cookie: bool = False  # RENJU_SECURE_COOKIE
    busy_timeout_ms: int = 5000
    sse_heartbeat_s: int = 15

    # Движковые процессы (rj-899): предварительные, калибруются. kill_grace_s — выше.
    engine_idle_timeout_s: float = 180.0  # гасим процесс партии по неактивности
    engine_sweep_interval_s: float = 30.0  # период idle-sweep

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path if self.db_path is not None else self.data_dir / "db.sqlite"

    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        f = self.data_dir / ".secret_key"
        if f.exists():
            return f.read_text().strip()
        key = secrets.token_hex(32)
        f.write_text(key)
        f.chmod(0o600)
        return key

    def resolved_rapfi_bin(self) -> Path:
        """Явный путь из env или самый свежий собранный бинарь."""
        if self.rapfi_bin is not None:
            return self.rapfi_bin
        candidates = sorted(
            REPO_ROOT.glob("engine/rapfi/Rapfi/build/*/pbrain-rapfi"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(
                "pbrain-rapfi не найден: собери движок (engine/build.sh) или укажи RENJU_RAPFI_BIN"
            )
        return candidates[0]
