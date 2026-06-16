# Engine-config бэкенд (rj-8py) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) или superpowers:executing-plans для реализации task-by-task. Шаги — чекбоксы (`- [ ]`).

**Goal:** Бэк админ-настроек движка: уровни (сила/время) + глобальный NNUE в БД; каждая партия замораживает свой конфиг при создании и играет под ним; `/admin/engine-config` GET/PUT; правки — только к новым партиям, без рестарта.

**Architecture:** Текущие настройки уровней — в БД (`levels` + `engine_settings`), редактируются админом. Партия при создании СНИМАЕТ свой конфиг `{level_id, strength, timeout_ms, nnue}` в Engine-контроллер (его форму владеет `app/game/controllers.py` после рефактора) — снимок неизменяем, даёт историю и «только к новым». Движок принимает только TOML: на запуск процесса партии её TOML собирается из базового шаблона (`engine/config.toml`) + флага nnue, пишется под `data_dir` и передаётся в `--config`; путь запоминается на слоте реестра, `_respawn` берёт его же.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy async / Alembic / pydantic / pytest (последовательно — shared Rapfi-процесс). Источник дизайна: `docs/superpowers/specs/2026-06-16-engine-config-design.md`.

---

## Целевая структура файлов

```
backend/app/
  models/
    level.py            # НОВЫЙ: Level (id,name,ordering,strength,timeout_ms) + EngineSettings (nnue, single-row)
  game/
    controllers.py      # MODIFY: Engine-контроллер несёт замороженный конфиг {level_id,strength,timeout_ms,nnue}
    players.py          # MODIFY: EngineParams из контроллера, не из levels-словаря
    service.py          # MODIFY: create_game снимает текущий конфиг уровня в контроллер
    deps.py             # MODIFY: убрать levels-словарь из сборки сервиса (параметры — из партии)
  config_repository.py  # НОВЫЙ: DAL — чтение уровней/nnue, атомарный апдейт, резолв «текущего конфига уровня»
  rapfi/
    engine_config_file.py # НОВЫЙ: сборка TOML партии из базового шаблона + nnue, запись под data_dir
    registry.py         # MODIFY: config-путь на слот; mark_present/compute_move/forbidden_points несут его; _respawn — со слота
    process.py          # без изменений (spawn уже принимает config_path)
  routers/
    admin.py            # MODIFY: + GET/PUT /api/admin/engine-config
  dtos/ или game/dtos.py # НОВЫЙ DTO engine-config (level rows + nnue)
backend/alembic/versions/<rev>_engine_config.py  # НОВЫЙ: таблицы + сид из levels.toml + бэкфилл game-контроллеров
```

## Вне области этого плана (СОЗНАТЕЛЬНО)

- **Фронт `rj-h1p`** (каркас админки + экран «Движок») — отдельный план.
- **Per-user конфиги; add/delete уровней; вкладки Пользователи (rj-6vk)/Состояние (rj-1in); админ-управление партиями** — см. §5 спеки.
- **Версионирование admin-настроек** — НЕ делаем: неизменяемость и история живут в снимке партии (контроллере); таблицы уровней хранят ТЕКУЩИЕ значения (правятся на месте).

## Конвенции

- TDD: тест → красный → минимальная реализация → зелёный → коммит. Из `backend/`.
- pytest ПОСЛЕДОВАТЕЛЬНО: `uv run pytest -q`. Линт: `uv run ruff check app tests && uv run ruff format app tests`. Тип: `uv run pyright app`.
- Относительные импорты в стиле файлов. Пользовательские данные в логах — через `app.logging_utils.safe`.
- Ветка одна: `feat/engine-config` (уже на ней). Коммит в конце каждого среза.
- Поведенческая нейтральность НЕ требуется (это фича) — но существующие тесты держим зелёными, кроме тех, что СОЗНАТЕЛЬНО меняем (живой lookup уходит).

---

## Slice B1 — DB: уровни + глобальный NNUE, миграция + сид

**Files:**
- Create: `backend/app/models/level.py`
- Create: `backend/alembic/versions/<rev>_engine_config.py`
- Test: `backend/tests/unit/test_level_model.py`, `backend/tests/unit/test_migration.py` (дополнить)

- [ ] **Step 1: Падающий тест модели**

Создать `backend/tests/unit/test_level_model.py`:

```python
from app.models.level import Level, EngineSettings


def test_level_columns():
    lv = Level(id="novice", name="Новичок", ordering=0, strength=5, timeout_ms=1000)
    assert (lv.id, lv.strength, lv.timeout_ms, lv.ordering) == ("novice", 5, 1000, 0)


def test_engine_settings_single_row():
    s = EngineSettings(id=1, nnue=True)
    assert s.id == 1 and s.nnue is True
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/unit/test_level_model.py -q`
Expected: FAIL (ModuleNotFoundError: app.models.level).

- [ ] **Step 3: Модель**

Создать `backend/app/models/level.py`:

```python
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class Level(Base):
    """Текущие настройки уровня сложности (правит админ). Набор фиксирован (сид из levels.toml)."""

    __tablename__ = "levels"

    id: Mapped[str] = mapped_column(primary_key=True)  # "novice".."god"
    name: Mapped[str]
    ordering: Mapped[int]  # порядок показа (слабый→сильный)
    strength: Mapped[int]  # INFO strength 0..100
    timeout_ms: Mapped[int]  # INFO timeout_turn, мс


class EngineSettings(Base):
    """Глобальные настройки движка (одна строка, id=1). Сейчас — только NNUE on/off."""

    __tablename__ = "engine_settings"

    id: Mapped[int] = mapped_column(primary_key=True)  # всегда 1
    nnue: Mapped[bool] = mapped_column(default=True)
```

- [ ] **Step 4: Зелёный + регистрация модели в тестовой metadata**

В `backend/tests/conftest.py`:
- Регистрация модели: добавить `import app.models.level  # noqa: F401` в фикстуры `engine` (~стр.30-32) и `app` (~стр.56-58) — иначе таблицы не попадут в `Base.metadata`.
- **Сид уровней под `app`/`client` (КРИТИЧНО):** фикстуры поднимают схему через `Base.metadata.create_all`, НЕ через alembic → `bulk_insert`-сид миграции в тестах НЕ выполняется, таблица `levels` пуста, и после B2 API-тесты (`POST /api/games`, `/api/levels`, admin GET) упадут на пустых уровнях. В фикстуре `app` ПОСЛЕ `create_all` засеять 7 уровней + `EngineSettings(id=1, nnue=True)` (общий хелпер `_seed_levels(session)`, те же значения, что в миграции B1). Без этого suite B2/B4 красный.
Run: `cd backend && uv run pytest tests/unit/test_level_model.py -q` → PASS.

- [ ] **Step 5: Миграция (таблицы + сид + бэкфилл — сид здесь, бэкфилл в B2)**

Сгенерировать ревизию: `cd backend && uv run alembic revision -m "engine_config"` (создаст файл в `alembic/versions/`). Заполнить `upgrade()`/`downgrade()` ВРУЧНУЮ (autogenerate может не видеть; пишем явно), `down_revision = "eab503b3e51b"` (текущий head — проверить `uv run alembic heads`):

```python
def upgrade() -> None:
    op.create_table(
        "levels",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("ordering", sa.Integer(), nullable=False),
        sa.Column("strength", sa.Integer(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
    )
    op.create_table(
        "engine_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nnue", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    # сид уровней из текущего levels.toml (значения фиксируем явно — миграция не должна
    # зависеть от файла, который позже может уйти)
    levels = sa.table(
        "levels",
        sa.column("id"), sa.column("name"), sa.column("ordering"),
        sa.column("strength"), sa.column("timeout_ms"),
    )
    op.bulk_insert(levels, [
        {"id": "novice", "name": "Новичок", "ordering": 0, "strength": 5, "timeout_ms": 1000},
        {"id": "easy", "name": "Лёгкий", "ordering": 1, "strength": 15, "timeout_ms": 1500},
        {"id": "low_medium", "name": "Ниже среднего", "ordering": 2, "strength": 35, "timeout_ms": 2000},
        {"id": "high_medium", "name": "Выше среднего", "ordering": 3, "strength": 55, "timeout_ms": 2500},
        {"id": "hard", "name": "Сложный", "ordering": 4, "strength": 75, "timeout_ms": 4000},
        {"id": "master", "name": "Мастер", "ordering": 5, "strength": 90, "timeout_ms": 6000},
        {"id": "god", "name": "Бог", "ordering": 6, "strength": 100, "timeout_ms": 7000},
    ])
    op.bulk_insert(
        sa.table("engine_settings", sa.column("id"), sa.column("nnue")),
        [{"id": 1, "nnue": True}],
    )
    # бэкфилл game.controllers — в Slice B2 (отдельная ревизия или этот же upgrade, см. B2 Step 6)


def downgrade() -> None:
    op.drop_table("engine_settings")
    op.drop_table("levels")
```

(Значения сида — точная копия `backend/levels.toml` на момент написания. Сверить с файлом перед коммитом.)

- [ ] **Step 6: Прогон миграции на чистой БД + suite**

Run: `cd backend && uv run alembic upgrade head` (на временной/тестовой БД — `RENJU_DATA_DIR` в tmp) и `uv run pytest -q`.
Expected: миграция применяется; suite зелёный (новые таблицы не ломают существующее).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/level.py backend/alembic/versions/ backend/tests/unit/test_level_model.py backend/tests/conftest.py
git commit -m "feat(rj-8py): DB-модель уровней + глобальный NNUE, миграция + сид"
```

---

## Slice B2 — Заморозка конфига в партию + параметры из контроллера

**Files:**
- Create: `backend/app/config_repository.py`
- Modify: `backend/app/game/controllers.py` (Engine несёт `{level_id, strength, timeout_ms, nnue}`)
- Modify: `backend/app/game/service.py` (`create_game` снимает конфиг), `backend/app/game/players.py` (params из контроллера), `backend/app/game/deps.py` (убрать levels-словарь)
- Modify: миграция B1 (бэкфилл существующих game.controllers) ИЛИ новая ревизия
- Test: `backend/tests/unit/test_controllers.py` (дополнить), `test_config_repository.py` (новый), `test_game_service_contour.py` (создание партии)

- [ ] **Step 1: Падающий тест — Engine-контроллер несёт замороженный конфиг**

Дополнить `backend/tests/unit/test_controllers.py`:

```python
from app.game.controllers import Engine, controller_from_json, controller_to_json


def test_engine_carries_frozen_config():
    e = Engine(level_id="master", strength=90, timeout_ms=6000, nnue=True)
    j = controller_to_json(e)
    assert j == {"kind": "engine", "level_id": "master", "strength": 90, "timeout_ms": 6000, "nnue": True}
    assert controller_from_json(j) == e
```

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/unit/test_controllers.py::test_engine_carries_frozen_config -q`
Expected: FAIL (Engine.__init__ takes no strength/...).

- [ ] **Step 3: Расширить Engine-контроллер**

В `backend/app/game/controllers.py`:

```python
@dataclass(frozen=True)
class Engine:
    level_id: str
    strength: int
    timeout_ms: int
    nnue: bool
```

`controller_to_json`: для Engine → `{"kind":"engine","level_id":c.level_id,"strength":c.strength,"timeout_ms":c.timeout_ms,"nnue":c.nnue}`.
`controller_from_json`: для `kind=="engine"` → `Engine(d["level_id"], d["strength"], d["timeout_ms"], d["nnue"])`.
Аксессоры `engine_level_id`/`engine_level_tag`/`public_view`/`_engines` — не трогаем (читают `.level_id`). **Добавить аксессор** `engine_nnue(controllers) -> bool | None` (по образцу `engine_level_tag`/`_engines`) — им B3 достаёт `nnue` партии для реестра, без ad-hoc разбора dict.

- [ ] **Step 4: Тест зелёный**

Run: `cd backend && uv run pytest tests/unit/test_controllers.py -q` → PASS.

- [ ] **Step 5: DAL конфига + создание партии снимает конфиг**

Создать `backend/app/config_repository.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models.level import EngineSettings, Level


class ConfigRepository:
    def __init__(self, session: AsyncSession):
        self._s = session

    async def levels(self) -> list[Level]:
        return list((await self._s.execute(select(Level).order_by(Level.ordering))).scalars())

    async def get_level(self, level_id: str) -> Level | None:
        return await self._s.get(Level, level_id)

    async def nnue(self) -> bool:
        s = await self._s.get(EngineSettings, 1)
        return bool(s.nnue) if s is not None else True
```

Тест `backend/tests/unit/test_config_repository.py` через `session`-фикстуру. ВАЖНО: `session`/`engine`-фикстуры поднимают схему через `Base.metadata.create_all`, БЕЗ сид-данных (alembic-сид не выполняется) → **тест сам засевает строки** перед ассертами: вызвать `_seed_levels(session)` (тот же conftest-хелпер, что в `app`-фикстуре) или вставить `Level`×7 + `EngineSettings(id=1, nnue=True)` руками. Затем: `levels()` упорядочены по `ordering`, `get_level("master").strength == 90`, `nnue() is True`.

**Резолв при создании — в роутере `POST /api/games`** (`routers/games.py`): он уже держит `request`+сессию и валидирует `levelId`. Там через `ConfigRepository(session)` берём текущий конфиг уровня X + глобальный `nnue`, формируем замороженный снимок `{level_id, strength, timeout_ms, nnue}` и передаём его в `create_game` (сигнатура `create_game` принимает готовый снимок вместо строки `opponent_level`). Так `GameService` БД для конфига не трогает — снимок приходит готовым из роутера.

- [ ] **Step 6: Параметры партии — из контроллера**

`backend/app/game/players.py` `make_player`: для Engine-контроллера строить `EngineParams(strength=ctl.strength, timeout_turn_ms=ctl.timeout_ms)` ИЗ контроллера, а не `levels[ctl.level_id]`. Убрать параметр `levels` из `make_player`/`EnginePlayer`/`GameService._players`/`deps.make_game_service`.
**Перевести на БД и убрать файловый путь уровней целиком** (иначе второй источник правды + мёртвый код):
- `GET /api/levels` (`routers/games.py` — отдаёт уровни фронту) и валидация `levelId` при создании — читать из `ConfigRepository(session)`, не из `request.app.state.levels`.
- По завершении B2 УДАЛИТЬ: загрузку `app.state.levels` (`app_factory.py:67`), `app/levels_config.py` (`load_levels`/`resolve_level`/`LevelInfo`), `backend/levels.toml`, `levels_file` из `config.py`, И тест `tests/unit/test_levels_config.py` (импортирует удаляемый модуль → иначе ImportError на сборе). Проверить отсутствие импортёров по `app` И `tests`: `grep -rn 'levels_config\|app.state.levels\|levels_file' app tests`.

- [ ] **Step 7: Бэкфилл существующих партий (в миграции)**

Дополнить `upgrade()` миграции B1 (после сидов): `conn = op.get_bind()`, по каждой строке `games` распарсить JSON `controllers`; у engine-стороны с РЕЗОЛВЯЩИМСЯ `level_id` дописать `strength/timeout_ms/nnue` (из засеянных уровней + `engine_settings.nnue`), записать обратно. **Пропускать стороны без уровня:** user-контроллеры, engine с `level_id="-"` (placeholder) или неизвестным id — НЕ падать на `None`. Если игр в БД нет — цикл пуст.
**Тест бэкфилла обязателен** (на пустой БД цикл пуст → иначе не покрыт): в `tests/unit/test_migration.py` (или новом) ДО `upgrade` на ревизии-перед-нашей вставить игру со старым `Engine(level_id)`-контроллером (без frozen-полей) → `alembic upgrade head` → проверить, что у engine-стороны появились `strength/timeout_ms/nnue` из сида. Доп. кейс: партия с engine `level_id="-"` — миграция её пропускает, не падает.

- [ ] **Step 8: Suite + линт + тип**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run pyright app`
Expected: PASS. Тесты создания партии/ходов используют новый контроллер; обновить ВСЕ места ручной сборки `Engine(level_id)`: `test_game_service_contour.py` (`_CTL` + инлайн-конструкторы, их несколько) И `test_players.py` (`Engine("master")` + `make_player(..., levels, ...)`) — добавить frozen-поля / снять параметр `levels`.

- [ ] **Step 9: Commit**

```bash
git add -A backend/app backend/tests backend/alembic
git commit -m "feat(rj-8py): заморозка конфига в партию (Engine-контроллер); параметры из партии, не из app.state.levels"
```

---

## Slice B3 — Реестр: TOML-на-партию (сборка + проводка до спавна/респавна)

**Files:**
- Create: `backend/app/rapfi/engine_config_file.py`
- Modify: `backend/app/rapfi/registry.py` — конструктор получает `data_dir`; `EngineSlot.config_path`; операции, поднимающие процесс, несут `nnue: bool | None = None`; **`_spawn_into` СОБИРАЕТ файл** партии (`build_engine_config` под `data_dir`) и кладёт путь на слот; `_spawn_into`/`_respawn` спавнят под `slot.config_path or self._config`; **`_terminate` УДАЛЯЕТ файл** (`remove_engine_config`).
- Modify: `backend/app/app_factory.py` — при создании `EngineRegistry` передать `data_dir=settings.data_dir`.
- Modify (вся цепочка проводки `nnue`, иначе `pyright app` красный): `backend/app/game/ports.py` (Protocol `EngineAdapter`: `nnue: bool | None = None` в `compute_move`/`forbidden_points`); `backend/app/game/moves.py` (`engine_move` пробрасывает); `backend/app/game/players.py` (`EnginePlayer`/`make_player` несут `nnue` из Engine-контроллера); `backend/app/game/service.py` (`fouls`→`forbidden_points`); `backend/app/routers/games.py` (`enter`→`mark_present(nnue=...)`).
- **`nnue` ОПЦИОНАЛЬНЫЙ** (`bool | None = None`, keyword): фейки (`conftest._FakeAdapter`) и fallback не ломаются; `None` → спавн под `self._config` (базовый шаблон = nnue-on). Расширяемо: позже к `nnue` добавятся прочие file-настройки (свопы и т.п.).
- Test: `backend/tests/unit/test_engine_config_file.py` (новый), `backend/tests/unit/test_registry.py` (дополнить), `backend/tests/integration/test_registry_live.py` (rate-over-N, см. rj-xv1)

- [ ] **Step 1: Падающий тест сборки TOML**

Создать `backend/tests/unit/test_engine_config_file.py`:

```python
from pathlib import Path

from app.rapfi.engine_config_file import build_engine_config

BASE_TOML = (
    '[general]\ncoord_conversion_mode = "none"\n'
    '[model]\nbinary_file = "rapfi/Networks/classical/model210901.bin"\n'
    '[model.evaluator]\ntype = "mix9svq"\n'
    '[[model.evaluator.weights]]\nweight_file = "rapfi/Networks/mix9svq/w.bin.lz4"\n'
)


def _base(tmp_path: Path) -> Path:
    p = tmp_path / "engine" / "config.toml"
    p.parent.mkdir(parents=True)
    p.write_text(BASE_TOML)
    return p


def test_nnue_on_keeps_evaluator(tmp_path: Path):
    p = build_engine_config(nnue=True, game_id="g1", data_dir=tmp_path, base_path=_base(tmp_path))
    text = p.read_text()
    assert "[model.evaluator]" in text and 'type = "mix9svq"' in text


def test_nnue_off_drops_evaluator(tmp_path: Path):
    p = build_engine_config(nnue=False, game_id="g1", data_dir=tmp_path, base_path=_base(tmp_path))
    text = p.read_text()
    assert "[model.evaluator]" not in text
    assert "binary_file" in text and 'coord_conversion_mode = "none"' in text


def test_weight_paths_absolute(tmp_path: Path):
    base = _base(tmp_path)
    text = build_engine_config(nnue=True, game_id="g1", data_dir=tmp_path, base_path=base).read_text()
    # модель/веса переписаны в абсолютные (резолв от base.parent = .../engine)
    assert str(base.parent / "rapfi/Networks/classical/model210901.bin") in text
```

(BASE_TOML — короткий валидный фрагмент; в проде шаблон — `engine/config.toml`.)

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/unit/test_engine_config_file.py -q`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Сборка TOML**

Создать `backend/app/rapfi/engine_config_file.py`:
- `build_engine_config(*, nnue: bool, game_id: str, data_dir: Path, base_path: Path) -> Path` — читает базовый TOML (`engine/config.toml` по `base_path`), при `nnue=False` УБИРАЕТ секцию `[model.evaluator]` и её `[[model.evaluator.weights]]` (оставляя `[model] binary_file`), пишет `data_dir / "engine_configs" / f"{game_id}.toml"`, возвращает путь. Каталог создавать (`mkdir parents exist_ok`).
  - **CRITICAL: пути весов/модели — в АБСОЛЮТНЫЕ.** Движок резолвит `binary_file`/`weight_file*` относительно КАТАЛОГА конфиг-файла (CLAUDE.md). Раз файл уезжает из `engine/` под `data_dir`, эти пути сломаются. Поэтому при сборке резолвить `[model] binary_file` и все `weight_file`/`weight_file_black`/`weight_file_white` в абсолютные (от `base_path.parent` = `engine/`) и записать абсолютными в собранный TOML.
  - Парсинг/правка: `tomllib` для чтения + пересборка ИЛИ текстовая правка — на выбор, детерминированно (с учётом переписывания путей).
- `remove_engine_config(game_id: str, data_dir: Path) -> None` — удалить файл партии (best-effort, `Path.unlink(missing_ok=True)`); зовётся РЕЕСТРОМ в `_terminate` (гашение процесса: leave/idle/delete) — файл живёт ровно сессию.
- **Тест (Step 1) обязан проверять структурную валидность** через `tomllib.loads(p.read_text())` (не только подстроки) + что в off-сборке остались `[model] binary_file` и `coord_conversion_mode="none"`.
NB: домен не трогаем — это `app/rapfi` (I/O-слой).

- [ ] **Step 4: Тест зелёный**

Run: `cd backend && uv run pytest tests/unit/test_engine_config_file.py -q` → PASS.

- [ ] **Step 5: Реестр — сборка файла при спавне, удаление в `_terminate`**

В `backend/app/rapfi/registry.py`:
- Конструктор `__init__`: принять `data_dir: Path` (сохранить `self._data_dir`); в `app_factory.py` передать `data_dir=settings.data_dir`.
- `EngineSlot` (≈стр.56-66): добавить `config_path: Path | None = None`.
- `mark_present(game_id, level_tag="-", *, nnue: bool | None = None)`, `compute_move(..., *, nnue: bool | None = None)`, `forbidden_points(..., *, nnue: bool | None = None)`: новый kwarg; прокинуть в `_claim(..., nnue)`.
- **Сборка при спавне** (`_spawn_into`): если `nnue is not None` и `slot.config_path is None` → `slot.config_path = build_engine_config(nnue=nnue, game_id=game_id, data_dir=self._data_dir, base_path=self._config)`. Спавн под `slot.config_path or self._config` (`None` → базовый шаблон). Существующему слоту путь НЕ пересобираем (immutable на сессию).
- `_respawn`: спавн под `slot.config_path or self._config` (файл жив всю сессию).
- **Удаление в `_terminate`:** после гашения процесса — `remove_engine_config(game_id, self._data_dir)` (best-effort). Так файл уходит со ВСЕМИ путями выхода — `mark_absent`(leave)/`sweep`(idle)/`release`(delete)/`close`/`_discard_slot` все идут через `_terminate`.
- `RapfiProcess.spawn` уже принимает `config_path` — не меняем.

Вызывающие достают `nnue` из Engine-контроллера партии и передают: `routers/games.py` `enter`→`mark_present(nnue=...)`; `game/moves.py` `engine_move`→`compute_move(nnue=...)`; `game/service.py` `fouls`→`forbidden_points(nnue=...)`. **Уборки в `delete_game`/ретеншн НЕ делаем** — файл привязан к процессу и чистится в `_terminate` (удаление партии гасит процесс штатно — через idle-sweep, как и сейчас).

- [ ] **Step 6: Тесты реестра (unit + live rate-over-N)**

Дополнить `tests/unit/test_registry.py`: **обновить `make_registry`** — передать `data_dir=tmp_path` (конструктор теперь требует его) и Path-конфиг с валидным base-TOML (для новых config-path-тестов); фейк-spawn фиксирует `config_path`. Проверить: (а) спавн партии под собранный путь; (б) **`_respawn` берёт `slot.config_path`**, а не глобальный (форс-respawn → тот же путь); (в) `_terminate` удаляет файл. `tests/integration/test_registry_live.py`: партия с nnue=off реально стартует (rate-over-N, без завязки на ход — см. rj-xv1).
**Фейки адаптера принимают `nnue` (иначе TypeError):** дописать kwarg `nnue=None` (или `**kw`) в `compute_move`/`forbidden_points`/`mark_present` у `conftest._FakeAdapter` (`conftest.py:85/88/101`), фейков в `test_game_service_contour.py`, `test_game_service.py`, `test_players.py`, И у `PresenceAdapter` в `tests/api/test_games_endpoints.py:81` (он ПЕРЕОПРЕДЕЛЯЕТ `mark_present` — правка базового фейка его не покрывает; `test_enter_leave_call_registry` зовёт `enter`→`mark_present(nnue=...)`). Вызывающие теперь передают `nnue=...`; опциональность kwarg НЕ спасает фейк, который параметр не объявил.

- [ ] **Step 7: Suite + линт + тип, Commit**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run pyright app`

```bash
git add -A backend/app backend/tests
git commit -m "feat(rj-8py): TOML-на-партию — сборка под data_dir, путь на слоте реестра, respawn тем же файлом"
```

---

## Slice B4 — Эндпоинт /admin/engine-config (GET/PUT)

**Files:**
- Modify: `backend/app/routers/admin.py` (+ GET/PUT), `backend/app/services/admin_service.py` (или `config_repository.py` — атомарный апдейт)
- Create: DTO (в `backend/app/game/dtos.py` или `backend/app/dtos/engine_config.py`)
- Test: `backend/tests/api/test_admin_engine_config.py` (новый)

- [ ] **Step 1: Падающий тест эндпоинта**

Создать `backend/tests/api/test_admin_engine_config.py` (образец admin-тестов — `tests/api/test_admin_users.py`): admin логинится → `GET /api/admin/engine-config` отдаёт уровни (id/name/strength/timeout_ms) + `nnue`; `PUT` с новыми strength/timeout/nnue → GET отражает изменения; не-admin → 403; невалидный strength (>100) → 422.

- [ ] **Step 2: Запустить — падает**

Run: `cd backend && uv run pytest tests/api/test_admin_engine_config.py -q`
Expected: FAIL (404 — эндпоинта нет).

- [ ] **Step 3: DTO + апдейт в config_repository**

DTO (pydantic): `LevelConfigDTO {id, name, strength, timeout_ms}`, `EngineConfigDTO {levels: list[LevelConfigDTO], nnue: bool}`; тело PUT: `{levels: [{id, strength, timeout_ms}], nnue: bool}` с валидацией (`strength` 0..100; `timeout_ms` 200..30000).
`ConfigRepository.update(levels: list[...], nnue: bool)`: в ОДНОЙ транзакции обновить строки `levels` (по id) + `engine_settings.nnue`; коммит один. (Атомарность — §3 спеки.) **Неизвестный `level_id` в теле → 422** (а не тихий no-op): проверить, что все присланные id существуют, иначе ошибка. Полный набор уровней не обязателен — обновляются присланные; nnue применяется глобально.

- [ ] **Step 4: Эндпоинт в admin.py**

В `backend/app/routers/admin.py` (гейт `admin_user` уже есть, стр.16-17):

```python
@router.get("/engine-config", response_model=EngineConfigDTO)
async def get_engine_config(_: Annotated[CurrentUser, Depends(admin_user)],
                            session: Annotated[AsyncSession, Depends(get_session)]):
    repo = ConfigRepository(session)
    return EngineConfigDTO(levels=[...], nnue=await repo.nnue())

@router.put("/engine-config", response_model=EngineConfigDTO)
async def put_engine_config(body: EngineConfigBody, _: Annotated[CurrentUser, Depends(admin_user)],
                            session: Annotated[AsyncSession, Depends(get_session)]):
    repo = ConfigRepository(session)
    await repo.update(body.levels, body.nnue)
    return EngineConfigDTO(levels=[...], nnue=await repo.nnue())
```

(Точные импорты/форму DTO привести в соответствие; валидация границ — pydantic `Field(ge=0, le=100)` / `ge=200, le=30000`.)

- [ ] **Step 5: Тест зелёный + suite + линт + тип**

Run: `cd backend && uv run pytest -q && uv run ruff check app tests && uv run pyright app` → PASS.

- [ ] **Step 6: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "feat(rj-8py): эндпоинт /admin/engine-config (GET/PUT, атомарно, admin-гейт, валидация)"
```

---

## Финальная проверка (rj-8py)

- [ ] Полный `uv run pytest -q` зелёный; `ruff` чисто; `pyright app` 0 ошибок.
- [ ] Ручная проверка (Alexey): создать партию на уровне → сыграть (движок поднимается под TOML партии); `PUT` меняет силу уровня → НОВАЯ партия идёт с новыми числами, старая — со своими; nnue=off реально запускает классику (живой прогон).

## Self-review

- **Покрытие спеки:** уровни+nnue в БД (B1) ✓; заморозка конфига в партию + параметры из партии, живой lookup уходит (B2) ✓; TOML-на-партию под data_dir + путь на слоте + respawn со слота (B3) ✓; GET/PUT атомарно/валидация/admin-гейт (B4) ✓; «только к новым» — из неизменяемого снимка контроллера ✓; миграция+сид+бэкфилл (B1/B2) ✓.
- **Форма хранения:** снимок в Engine-контроллере (inline) — выбрана из свободных вариантов спеки §2/§8; версионирование не требуется.
- **Открытые для исполнителя (детерминировать при реализации, не placeholder):** способ вырезки секции `[model.evaluator]` (tomllib+пересборка vs текст) — на выбор, с тестом on/off; точная проводка `ConfigRepository` в `create_game` (через deps); уборка TOML-файлов партий (при удалении партии) — добавить в delete-путь.
