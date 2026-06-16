import tomllib
from pathlib import Path

from app.rapfi.engine_config_file import build_engine_config, remove_engine_config

BASE_TOML = (
    '[general]\ncoord_conversion_mode = "none"\n'
    '[model]\nbinary_file = "rapfi/Networks/classical/model210901.bin"\n'
    '[model.evaluator]\ntype = "mix9svq"\n'
    '[[model.evaluator.weights]]\nweight_file = "rapfi/Networks/mix9svq/w.bin.lz4"\n'
)


def test_nnue_on_keeps_evaluator(tmp_path: Path):
    p = build_engine_config(nnue=True, game_id="g1", data_dir=tmp_path, base=BASE_TOML)
    cfg = tomllib.loads(p.read_text())  # структурно валиден
    assert cfg["model"]["evaluator"]["type"] == "mix9svq"
    assert cfg["general"]["coord_conversion_mode"] == "none"


def test_nnue_off_drops_evaluator(tmp_path: Path):
    p = build_engine_config(nnue=False, game_id="g1", data_dir=tmp_path, base=BASE_TOML)
    cfg = tomllib.loads(p.read_text())
    assert "evaluator" not in cfg["model"]  # секция убрана
    assert (
        cfg["model"]["binary_file"] == "rapfi/Networks/classical/model210901.bin"
    )  # путь относительный, не трогаем
    assert cfg["general"]["coord_conversion_mode"] == "none"


def test_remove_engine_config(tmp_path: Path):
    p = build_engine_config(nnue=True, game_id="g2", data_dir=tmp_path, base=BASE_TOML)
    assert p.exists()
    remove_engine_config(game_id="g2", data_dir=tmp_path)
    assert not p.exists()
    # повторный вызов на отсутствующем файле не падает
    remove_engine_config(game_id="g2", data_dir=tmp_path)
