"""Build and remove per-game TOML config files for the Rapfi engine.

B3a: assembles a TOML from a base template string, optionally stripping
the [model.evaluator] section (and its [[model.evaluator.weights]] entries)
when nnue=False.  Paths inside the TOML are left untouched — cwd resolution
is handled by the caller (B3b).
"""

from __future__ import annotations

import re
from pathlib import Path


def build_engine_config(
    *,
    nnue: bool,
    game_id: str,
    data_dir: Path,
    base: str,
) -> Path:
    """Write a game-specific engine config TOML and return its path.

    Args:
        nnue:     When True the base TOML is written as-is (evaluator section
                  kept).  When False the ``[model.evaluator]`` section and its
                  ``[[model.evaluator.weights]]`` entries are removed.
        game_id:  Unique game identifier used as the file stem.
        data_dir: Root directory under which ``engine_configs/`` is created.
        base:     Full text of the template TOML.

    Returns:
        Path to the written file (``data_dir/engine_configs/<game_id>.toml``).
    """
    content = base if nnue else _drop_evaluator_section(base)

    out_dir = data_dir / "engine_configs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{game_id}.toml"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def remove_engine_config(game_id: str, data_dir: Path) -> None:
    """Delete the game's config file (best-effort; silent if missing)."""
    path = data_dir / "engine_configs" / f"{game_id}.toml"
    path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Matches the start of any TOML section header, e.g. "[foo]" or "[[foo]]"
_SECTION_START = re.compile(r"^\s*\[", re.MULTILINE)


def _drop_evaluator_section(toml_text: str) -> str:
    """Return *toml_text* with the [model.evaluator] block removed.

    The block consists of:
    - one ``[model.evaluator]`` header line
    - zero or more ``[[model.evaluator.weights]]`` sub-table entries

    Everything between that header and the next unrelated section (or EOF) is
    stripped.  All other sections are preserved verbatim.
    """
    lines = toml_text.splitlines(keepends=True)
    result: list[str] = []
    skip = False

    for line in lines:
        stripped = line.strip()

        # Detect start of the evaluator block (startswith — терпимо к трейлинг-комменту
        # вида "[model.evaluator] # ...", который точное сравнение пропустило бы)
        if stripped.startswith("[model.evaluator]") or stripped.startswith("[[model.evaluator."):
            skip = True
            continue

        if skip:
            # Stop skipping when we hit a new top-level or unrelated section
            if _SECTION_START.match(line):
                # Is it still part of model.evaluator?
                if stripped.startswith("[model.evaluator") or stripped.startswith(
                    "[[model.evaluator"
                ):
                    continue  # still inside evaluator block
                # New unrelated section — resume writing
                skip = False
                result.append(line)
            # else: key-value inside evaluator block — drop
            continue

        result.append(line)

    return "".join(result)
