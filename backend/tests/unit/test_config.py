from app.config import REPO_ROOT, Settings


def test_repo_root_points_to_repo():
    assert (REPO_ROOT / "engine").is_dir()
    assert (REPO_ROOT / "backend").is_dir()


def test_default_rapfi_config_path():
    s = Settings()
    assert s.rapfi_config == REPO_ROOT / "engine" / "config.toml"


def test_env_overrides_bin(monkeypatch, tmp_path):
    fake = tmp_path / "pbrain-rapfi"
    fake.touch()
    monkeypatch.setenv("RENJU_RAPFI_BIN", str(fake))
    assert Settings().resolved_rapfi_bin() == fake


def test_bin_discovery_picks_newest_build(monkeypatch, tmp_path):
    import os

    builds = tmp_path / "engine/rapfi/Rapfi/build"
    old = builds / "old-preset"
    new = builds / "new-preset"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "pbrain-rapfi").touch()
    os.utime(old / "pbrain-rapfi", (1, 1))
    monkeypatch.setattr("app.config.REPO_ROOT", tmp_path)
    monkeypatch.delenv("RENJU_RAPFI_BIN", raising=False)
    assert Settings().resolved_rapfi_bin() == new / "pbrain-rapfi"


def test_bin_discovery_fails_loudly_when_missing(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setattr("app.config.REPO_ROOT", tmp_path)
    monkeypatch.delenv("RENJU_RAPFI_BIN", raising=False)
    with pytest.raises(FileNotFoundError):
        Settings().resolved_rapfi_bin()
