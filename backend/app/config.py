"""Настройки приложения (pydantic-settings, env-префикс RENJU_)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RENJU_", env_file=".env", extra="ignore")

    rapfi_bin: Path | None = None  # RENJU_RAPFI_BIN
    rapfi_config: Path = REPO_ROOT / "engine" / "config.toml"  # RENJU_RAPFI_CONFIG
    levels_file: Path = REPO_ROOT / "backend" / "levels.toml"  # RENJU_LEVELS_FILE
    engine_kill_grace_s: float = 2.0  # сколько ждать terminate перед kill

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
