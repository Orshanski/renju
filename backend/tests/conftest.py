import pytest

from app.config import REPO_ROOT, Settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def rapfi_paths(settings):
    """(bin, config, cwd) реального движка; скип, если бинарь не собран."""
    try:
        bin_path = settings.resolved_rapfi_bin()
    except FileNotFoundError:
        pytest.skip("Rapfi binary not built — run engine/build.sh")
    if not settings.rapfi_config.exists():
        pytest.skip("engine/config.toml missing")
    return bin_path, settings.rapfi_config, REPO_ROOT
