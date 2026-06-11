# Уровни в конфиге · План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Вынести уровни сложности из кода (`Level` enum + `LEVELS` dict) в данные — файл `backend/levels.toml`, читаемый config-слоем; `app/domain/levels.py` переименовать в `engine_params.py` (остаётся только тип `EngineParams`).

**Architecture:** Уровни = метаданные (id/name/strength/timeout), произвольный набор. Домен знает только форму параметров движка (`EngineParams`); набор и значения — в TOML, грузятся config-слоем `app/levels_config.py` (I/O вне домена, §4.9). Читаются на старте партии, фиксируются на партию.

**Tech Stack:** Python 3.13, `tomllib` (stdlib, чтение), uv, pytest, ruff.

**Спека:** `docs/superpowers/specs/2026-06-11-levels-config-design.md`. Работать в feature-ветке `levels-config` (создать от `main` на Task 1; в `main` не коммитить).

---

### Task 1: config-слой `levels_config.py` + `levels.toml` (аддитивно, ничего не ломает)

Создаём новый модуль и файл данных. `Level`/`LEVELS` пока на месте — существующий код зелёный. `EngineParams` импортируем по текущему пути `app.domain.levels` (переименуем в Task 2).

**Files:**
- Create: `backend/levels.toml`
- Create: `backend/app/levels_config.py`
- Modify: `backend/app/config.py` (добавить поле `levels_file`)
- Test: `backend/tests/unit/test_levels_config.py`

- [ ] **Step 1: Падающий тест `backend/tests/unit/test_levels_config.py`**

```python
import pytest

from app.domain.levels import EngineParams  # в Task 2 путь станет app.domain.engine_params
from app.levels_config import LevelInfo, load_levels, resolve_level

_SAMPLE = """
[[levels]]
id = "novice"
name = "Новичок"
strength = 5
timeout_turn_ms = 1000

[[levels]]
id = "hard"
name = "Сложный"
strength = 75
timeout_turn_ms = 4000
"""


def test_load_levels_parses_ordered(tmp_path):
    f = tmp_path / "levels.toml"
    f.write_text(_SAMPLE)
    levels = load_levels(f)
    assert [lv.id for lv in levels] == ["novice", "hard"]  # порядок из файла
    assert levels[0] == LevelInfo(
        "novice", "Новичок", EngineParams(strength=5, timeout_turn_ms=1000)
    )
    assert levels[1].params.timeout_turn_ms == 4000


def test_resolve_level_hit_and_miss(tmp_path):
    f = tmp_path / "levels.toml"
    f.write_text(_SAMPLE)
    levels = load_levels(f)
    assert resolve_level(levels, "hard").name == "Сложный"
    assert resolve_level(levels, "nope") is None


def test_load_levels_empty_raises(tmp_path):
    f = tmp_path / "levels.toml"
    f.write_text("")  # синтаксически валиден, но пуст
    with pytest.raises(ValueError):
        load_levels(f)
```

- [ ] **Step 2: Убедиться, что падает**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_levels_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.levels_config'`.

- [ ] **Step 3: Реализовать `backend/app/levels_config.py`**

```python
"""Загрузка уровней сложности из TOML. config-слой (I/O), не домен (§4.9)."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.domain.levels import EngineParams  # Task 2: → app.domain.engine_params


@dataclass(frozen=True)
class LevelInfo:
    id: str
    name: str
    params: EngineParams


def load_levels(path: Path) -> list[LevelInfo]:
    """TOML-файл уровней → упорядоченный список (порядок записей = порядок уровней).

    Плоские поля записи (strength/timeout_turn_ms) собираются в EngineParams.
    Пустой набор → ValueError (иначе потребитель упадёт на levels[0])."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    levels = [
        LevelInfo(
            id=rec["id"],
            name=rec["name"],
            params=EngineParams(
                strength=rec["strength"], timeout_turn_ms=rec["timeout_turn_ms"]
            ),
        )
        for rec in data.get("levels", [])
    ]
    if not levels:
        raise ValueError(f"no levels defined in {path}")
    return levels


def resolve_level(levels: list[LevelInfo], level_id: str) -> LevelInfo | None:
    """LevelInfo по id, или None если нет такого уровня."""
    for lv in levels:
        if lv.id == level_id:
            return lv
    return None
```

- [ ] **Step 4: Создать `backend/levels.toml`** (стартовая 7-ступенчатая шкала)

```toml
# Уровни сложности. Порядок записей = порядок уровней (от слабого к сильному).
# strength: INFO strength движка, 0..100 (100 — без человеческого ослабления).
# Калибруется на живой игре; правка подхватывается следующей новой партией.

[[levels]]
id = "novice"
name = "Новичок"
strength = 5
timeout_turn_ms = 1000

[[levels]]
id = "easy"
name = "Лёгкий"
strength = 15
timeout_turn_ms = 1500

[[levels]]
id = "low_medium"
name = "Ниже среднего"
strength = 35
timeout_turn_ms = 2000

[[levels]]
id = "high_medium"
name = "Выше среднего"
strength = 55
timeout_turn_ms = 2500

[[levels]]
id = "hard"
name = "Сложный"
strength = 75
timeout_turn_ms = 4000

[[levels]]
id = "master"
name = "Мастер"
strength = 90
timeout_turn_ms = 6000

[[levels]]
id = "god"
name = "Бог"
strength = 100
timeout_turn_ms = 7000
```

- [ ] **Step 5: Добавить путь в `backend/app/config.py`**

В класс `Settings`, рядом с `rapfi_config` (после строки с `rapfi_config`):

```python
    levels_file: Path = REPO_ROOT / "backend" / "levels.toml"  # RENJU_LEVELS_FILE
```

- [ ] **Step 6: Прогнать тест + ruff**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_levels_config.py -v`
Expected: `3 passed`.
Run: `cd /Users/alexey/code/Renju/backend && uv run ruff check app/levels_config.py tests/unit/test_levels_config.py`
Expected: чисто.

- [ ] **Step 7: Ветка + commit**

```bash
git -C /Users/alexey/code/Renju checkout -b levels-config
git -C /Users/alexey/code/Renju add backend/app/levels_config.py backend/levels.toml backend/app/config.py backend/tests/unit/test_levels_config.py
git -C /Users/alexey/code/Renju commit -m "feat(levels): config layer — load levels from levels.toml" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: переименование `levels.py` → `engine_params.py` + все импортёры + play_cli (атомарно)

Убираем `Level`/`LEVELS`. Это ломает всех импортёров `LEVELS`/`Level` (play_cli, старый test_levels) и меняет путь `EngineParams` — поэтому правим всё в одной задаче, после неё всё зелёное.

**Files:**
- Rename: `backend/app/domain/levels.py` → `backend/app/domain/engine_params.py`
- Modify: `backend/app/rapfi/protocol.py`, `backend/app/rapfi/adapter.py`, `backend/app/levels_config.py` (импорт `EngineParams`)
- Modify: `backend/tests/unit/test_protocol.py`, `backend/tests/integration/test_adapter.py` (импорт + B1)
- Modify: `backend/scripts/play_cli.py` (уровни из конфига)
- Delete: `backend/tests/unit/test_levels.py`; перенести `test_params_immutable` → `backend/tests/unit/test_engine_params.py`

- [ ] **Step 1: Переименовать модуль и вычистить его до `EngineParams`**

```bash
git -C /Users/alexey/code/Renju mv backend/app/domain/levels.py backend/app/domain/engine_params.py
```

Содержимое `backend/app/domain/engine_params.py` — заменить целиком на:

```python
"""Параметры движка Rapfi для одного уровня. Чистый тип, без I/O."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineParams:
    strength: int  # INFO strength, 0..100 (100 — без человеческого ослабления)
    timeout_turn_ms: int  # INFO timeout_turn
```

- [ ] **Step 2: Обновить импорт `EngineParams` у всех потребителей**

Заменить `from app.domain.levels import EngineParams` → `from app.domain.engine_params import EngineParams` в:
- `backend/app/rapfi/protocol.py` (строка ~15)
- `backend/app/rapfi/adapter.py` (строка ~14)
- `backend/app/levels_config.py` (комментарий «Task 2» убрать)
- `backend/tests/unit/test_protocol.py` (строка 3)

В `backend/tests/integration/test_adapter.py` строка 6 сейчас:
```python
from app.domain.levels import LEVELS, EngineParams, Level
```
заменить на:
```python
from app.domain.engine_params import EngineParams
```
и в `test_real_levels_work_end_to_end` заменить вызов `LEVELS[Level.NOVICE]` на локальный `EngineParams(...)`:
```python
async def test_real_levels_work_end_to_end(adapter):
    move = await adapter.compute_move([(7, 7)], EngineParams(strength=10, timeout_turn_ms=1000))
    assert on_board(move)
```

- [ ] **Step 3: Переписать `backend/scripts/play_cli.py` на config-слой**

Заменить импорт-строку `from app.domain.levels import LEVELS, Level` на:
```python
from app.levels_config import LevelInfo, load_levels, resolve_level
```
(`from app.config import REPO_ROOT, Settings` уже есть.)

Сигнатуру и тело `game_loop` — взять уровень как `LevelInfo`:
```python
async def game_loop(level: LevelInfo) -> None:
    settings = Settings()
    adapter = RapfiAdapter(
        bin_path=settings.resolved_rapfi_bin(),
        config_path=settings.rapfi_config,
        cwd=REPO_ROOT,
    )
    params = level.params
    human = random.choice([Color.BLACK, Color.WHITE])
    colour = "чёрными ●" if human is Color.BLACK else "белыми ○"
    print(f"Уровень: {level.name}. Ты играешь {colour}.")
```
(остальное тело `game_loop` — без изменений; `params` уже определён.)

`main()` — читать уровни до argparse, choices/default из набора, резолв:
```python
def main() -> None:
    settings = Settings()
    levels = load_levels(settings.levels_file)  # пустой набор → ValueError
    ids = [lv.id for lv in levels]
    parser = argparse.ArgumentParser(description="Партия против Rapfi в терминале")
    parser.add_argument("--level", choices=ids, default=ids[0])
    args = parser.parse_args()
    level = resolve_level(levels, args.level)
    if level is None:  # choices гарантируют валидность; страховка
        parser.error(f"unknown level: {args.level}")
    asyncio.run(game_loop(level))
```

- [ ] **Step 4: Удалить старый `test_levels.py`, перенести immutability-тест**

```bash
git -C /Users/alexey/code/Renju rm backend/tests/unit/test_levels.py
```

Создать `backend/tests/unit/test_engine_params.py`:
```python
import pytest

from app.domain.engine_params import EngineParams


def test_engine_params_is_frozen():
    p = EngineParams(strength=50, timeout_turn_ms=2000)
    with pytest.raises(AttributeError):  # frozen dataclass → FrozenInstanceError (подкласс)
        p.strength = 99  # type: ignore[misc]
```

(Инвариант-тесты `test_strength_in_engine_range_and_monotonic` / `test_timeouts_positive` /
`test_all_levels_have_params` НЕ переносим — инварианты набора отложены в будущий
admin-валидатор, спека §«Валидация».)

- [ ] **Step 5: Полный прогон + ruff**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest -q`
Expected: всё зелёное (unit + integration против движка). Старого `test_levels.py` нет; `test_levels_config.py` и `test_engine_params.py` зелёные; `test_adapter`/`test_protocol` зелёные на новом импорте.
Run: `cd /Users/alexey/code/Renju/backend && uv run ruff check app tests scripts`
Expected: чисто (нет битых импортов `app.domain.levels`).

- [ ] **Step 6: Ручной smoke play_cli (исполнителю)**

Run: `cd /Users/alexey/code/Renju/backend && uv run python -m scripts.play_cli --help`
Expected: usage с `--level {novice,easy,low_medium,high_medium,hard,master,god}`, exit 0.
(NB: `main()` читает `levels.toml` до argparse — `--help` требует существующего
`backend/levels.toml`; нет файла / пустой → `ValueError`/`FileNotFoundError` до usage,
это норма по дизайну.)

- [ ] **Step 7: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/domain/engine_params.py backend/app/rapfi backend/app/levels_config.py backend/tests backend/scripts/play_cli.py
git -C /Users/alexey/code/Renju commit -m "refactor(levels): levels as data — rename levels.py->engine_params.py, play_cli reads config" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: финал — полный прогон, синхронизация спеки §4.5, линт

**Files:**
- Modify: `docs/superpowers/specs/2026-06-07-renju-design.md` (§4.5)
- Possibly modify: что подсветит ruff

- [ ] **Step 1: Полный прогон + формат-чек**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest -q`
Expected: всё зелёное.
Run: `cd /Users/alexey/code/Renju/backend && uv run ruff check app tests scripts && uv run ruff format --check app tests scripts`
Expected: чисто (если format жалуется — `uv run ruff format app tests scripts` + перепрогон).

- [ ] **Step 2: Синхронизировать основную спеку под новую модель**

В `docs/superpowers/specs/2026-06-07-renju-design.md`:
- **§4.5** (строки ~155–167): «enum-идентификатор уровня / Pydantic `Enum` на бэке» →
  уровни это **данные в `backend/levels.toml`** (id-строки, произвольный набор), `Level`
  enum в коде нет; `levelId` валидируется по загруженному набору (нет id → 422). Снять
  «Мастер = 100» как инвариант (строка 164) — максимум не требуется. Строки 165–167
  «калибровка через admin-UI» → калибровка идёт **правкой `levels.toml`** (читается на
  старте партии, без рестарта); admin-UI остаётся будущим (rj-tan, §4.7).
- **§5.1** (строка ~328): «только **enum-уровень** из server-side списка» → «только
  **id уровня** из server-side набора» (смысл тот же — клиент не задаёт сырые
  параметры движка; формулировку про enum снять).
- Сослаться на `2026-06-11-levels-config-design.md`.

- [ ] **Step 3: Commit (если что-то поправили)**

```bash
git -C /Users/alexey/code/Renju add backend docs/superpowers/specs/2026-06-07-renju-design.md
git -C /Users/alexey/code/Renju commit -m "docs(spec): sync §4.5 to levels-as-data; ruff pass" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Сверка с целью**

- `uv run pytest` зелёный целиком; `Level`/`LEVELS` нигде нет (`grep -rn 'LEVELS\|class Level' backend/app backend/scripts` — пусто).
- `backend/levels.toml` существует, 7 уровней; правка числа в нём → следующая новая `play_cli`-партия играет с новым strength (ручная проверка Alexey).
- `app/domain/engine_params.py` — только `EngineParams`; импортёры обновлены.

---

## Что сознательно НЕ в этом этапе

- Admin-UI редактор уровней + его валидатор (rj-tan) — с фронтом.
- HTTP `POST /games` / `GET /levels` (этапы 2–3) — здесь только домен/config + play_cli.
- Инвариант-валидация файла (strength 0..100, монотонность) — отложена в admin-валидатор; сейчас только «непустой набор».
- mtime-кэш / reload во время идущей партии — читаем на старте партии.
