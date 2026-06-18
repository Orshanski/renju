# Глубина поиска как параметр уровня — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить уровням параметр глубины поиска `max_depth` (рычаг ослабления под потолком силы), доставлять движку через `INFO max_depth`, дать админу крутить его в таблице уровней.

**Architecture:** Сила задаёт потолок глубины (`depth_ceiling(strength)`, формула `SkillMovePicker`). Глубина уровня — `int` 1…99, крутится в `[верх предыдущего уровня … потолок своей силы]`; Бог (сила 100, skill off) — `[16…99]`. Вся диапазонная логика и зажим силы — на фронте; бэк хранит число и шлёт движку, делает только санитизацию типа/границ. Параметр замораживается в партию (как `strength`/`timeout`/`nnue`).

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy / Alembic / SQLite (бэк, `backend/`, uv); React/TS/Vite (фронт, `frontend/`).

**Источник истины:** `docs/superpowers/specs/2026-06-18-level-depth-design.md`.

## Global Constraints

- `max_depth` — обычный `int` 1…99 ВЕЗДЕ (колонка, JSON-снимок, DTO). Никаких `None`/sentinel/«без капа».
- Бэк диапазонной логики/подстановки/зажима НЕ делает — только санитизация типа/границ (`int`, 1…99) для целостности (анти-инъекция). Диапазон/зажим — на фронте.
- В stdin движка уходит только провалидированный `int` (анти-инъекция, спека §5.2 / CLAUDE.md).
- Тесты гонять ПОСЛЕДОВАТЕЛЬНО (`uv run pytest -q`), не параллельно — shared state (процесс Rapfi).
- Команды бэка — из `backend/`. Линт/формат: `uv run ruff check app tests` · `uv run ruff format app tests`.
- Деплой катит миграции — новая Alembic-миграция обязательна для колонки.

---

## Task 1: Доменная функция `depth_ceiling`

**Files:**
- Create: `backend/app/domain/levels_depth.py`
- Test: `backend/tests/unit/test_levels_depth.py`

**Interfaces:**
- Produces: `depth_ceiling(strength: int) -> int` — потолок глубины для силы (формула `SkillMovePicker`, `skill.h:35-43`). `strength` 0…100 → 4…16.

- [ ] **Step 1: Написать падающий тест**

```python
# backend/tests/unit/test_levels_depth.py
import pytest
from app.domain.levels_depth import depth_ceiling


@pytest.mark.parametrize(
    "strength,expected",
    [
        (0, 4), (5, 4), (6, 4), (7, 5), (12, 5), (13, 6), (15, 6), (19, 6),
        (20, 7), (26, 7), (27, 8), (33, 8), (34, 9), (35, 9), (41, 9),
        (42, 10), (49, 10), (50, 11), (55, 11), (58, 11), (59, 12), (67, 12),
        (68, 13), (75, 13), (77, 13), (78, 14), (88, 14), (89, 15), (90, 15),
        (99, 15), (100, 16),
    ],
)
def test_depth_ceiling_matches_engine_formula(strength: int, expected: int):
    assert depth_ceiling(strength) == expected
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `uv run pytest tests/unit/test_levels_depth.py -q`
Expected: FAIL (`ModuleNotFoundError: app.domain.levels_depth`).

- [ ] **Step 3: Реализация**

```python
# backend/app/domain/levels_depth.py
"""Потолок глубины поиска для силы движка. Чистая логика, без I/O.

Формула снята с Rapfi SkillMovePicker (engine/rapfi/Rapfi/search/skill.h:35-43):
BaseDepth=4, FullDepth=16, Alpha=0.5 → k=(16-4)/(0.5-1)=-24,
targetDepth = 4 + int(-24*(0.5^(s/100) - 1)) = 4 + floor(24*(1 - 0.5^(s/100))).
strength 0..100 → 4..16. Движок применяет это как потолок поиска только при
strength<100 (при 100 skill выключен); в нашей модели — верх диапазона глубины уровня.
"""


def depth_ceiling(strength: int) -> int:
    return 4 + int(24 * (1 - 0.5 ** (strength / 100)))
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `uv run pytest tests/unit/test_levels_depth.py -q`
Expected: PASS (все параметры).

- [ ] **Step 5: Свериться с живым движком (разовая проверка факта, не CI-тест)**

Run: `uv run python scripts/engine_probes/probe_depth_vs_strength_raw.py check`
Expected: столбец «достигнуто» = заданной глубине для 1/2/3/4/8 — подтверждает, что `INFO max_depth` реально режет. (Формула уже сверена параметрами в Step 1; этот шаг — подтверждение механизма доставки.)

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/domain/levels_depth.py tests/unit/test_levels_depth.py
git commit -m "feat(levels): depth_ceiling — потолок глубины от силы (формула SkillMovePicker)"
```

---

## Task 2: `EngineParams.max_depth` + доставка `INFO max_depth`

**Files:**
- Modify: `backend/app/domain/engine_params.py`
- Modify: `backend/app/rapfi/protocol.py` (`tunable_commands`, ~101-103)
- Test: `backend/tests/unit/test_protocol.py` (добавить кейсы)

**Interfaces:**
- Consumes: ничего нового.
- Produces: `EngineParams(strength, timeout_turn_ms, max_depth=99)` — поле `max_depth: int = 99`. `tunable_commands(params)` теперь возвращает 3 строки, последняя `f"INFO max_depth {params.max_depth}"`.

- [ ] **Step 1: Написать падающий тест**

```python
# backend/tests/unit/test_protocol.py — добавить
from app.domain.engine_params import EngineParams
from app.rapfi.protocol import tunable_commands


def test_tunable_commands_includes_max_depth():
    cmds = tunable_commands(EngineParams(strength=5, timeout_turn_ms=1000, max_depth=2))
    assert cmds == ["INFO strength 5", "INFO timeout_turn 1000", "INFO max_depth 2"]


def test_engine_params_max_depth_defaults_to_99():
    p = EngineParams(strength=5, timeout_turn_ms=1000)
    assert p.max_depth == 99
    assert tunable_commands(p)[-1] == "INFO max_depth 99"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `uv run pytest tests/unit/test_protocol.py -k max_depth -q`
Expected: FAIL (`TypeError: unexpected keyword 'max_depth'` / нет 3-й команды).

- [ ] **Step 3: Реализация — `EngineParams`**

```python
# backend/app/domain/engine_params.py
@dataclass(frozen=True)
class EngineParams:
    strength: int  # INFO strength, 0..100 (100 — без человеческого ослабления)
    timeout_turn_ms: int  # INFO timeout_turn
    max_depth: int = 99  # INFO max_depth, 1..99 (99 = max_search_depth, потолок движка)
```

- [ ] **Step 4: Реализация — `tunable_commands`**

```python
# backend/app/rapfi/protocol.py
def tunable_commands(params: EngineParams) -> list[str]:
    """Per-move INFO (сила/время/глубина). Шлём перед каждым расчётом.

    max_depth — обычный int 1..99, в stdin движка только проверенный int (анти-инъекция)."""
    return [
        f"INFO strength {params.strength}",
        f"INFO timeout_turn {params.timeout_turn_ms}",
        f"INFO max_depth {params.max_depth}",
    ]
```

- [ ] **Step 5: Запустить — весь protocol-тест (доставка идёт и в cold через `init_commands`, и в warm через `incremental_move_commands`, обе зовут `tunable_commands` — отдельная правка не нужна)**

Run: `uv run pytest tests/unit/test_protocol.py -q`
Expected: PASS. **Обновить два теста с точным списком команд** (оба сломаются без `INFO max_depth 99`): `test_tunable_commands_per_move_info` (стр.171) и `test_init_commands` (стр.80 — `init_commands = [*start_commands(), *tunable_commands(params)]`, тоже включает per-move tunable). Добавить `"INFO max_depth 99"` в ожидаемые списки.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/domain/engine_params.py app/rapfi/protocol.py tests/unit/test_protocol.py
git commit -m "feat(engine): max_depth в EngineParams + INFO max_depth в tunable_commands"
```

---

## Task 3: Колонка `levels.max_depth` + Alembic-миграция (сид/бэкфилл)

**Files:**
- Modify: `backend/app/models/level.py` (`Level`)
- Create: `backend/alembic/versions/<rev>_level_max_depth.py`
- Test: `backend/tests/unit/test_migration.py` (добавить кейс) или `test_level_model.py`

**Interfaces:**
- Produces: `Level.max_depth: int` (NOT NULL). Сид/бэкфилл уровней = `depth_ceiling(strength)`. Бэкфилл `games.controllers` engine-стороны: `max_depth = depth_ceiling(ctl["strength"])` (от ЗАМОРОЖЕННОЙ силы партии).

- [ ] **Step 1: Добавить поле в модель**

```python
# backend/app/models/level.py — в class Level
    max_depth: Mapped[int]  # INFO max_depth, 1..99; верх диапазона = depth_ceiling(strength)
```

- [ ] **Step 2: Сгенерировать ревизию-заготовку**

Run: `uv run alembic revision -m "level max_depth"`
`down_revision` = вывод `uv run alembic heads` (ТЕКУЩИЙ head — **НЕ** `5d790f3dfeb5`: после него идёт миграция user_settings_v2). Подставить это значение и в код миграции (Step 3, поле `down_revision`), и в тест бэкфилла (Step 4) вместо `<DOWN_REVISION>`.

- [ ] **Step 3: Написать миграцию (формула инлайн — миграция самодостаточна, не импортирует app; прецедент `5d790f3dfeb5`)**

```python
# backend/alembic/versions/<rev>_level_max_depth.py
"""level max_depth"""
import json
import sqlalchemy as sa
from alembic import op

revision = "<rev>"
down_revision = "<HEAD>"  # подставить актуальный
branch_labels = None
depends_on = None


def _depth_ceiling(strength: int) -> int:
    return 4 + int(24 * (1 - 0.5 ** (strength / 100)))


def upgrade() -> None:
    # 1) колонка с временным дефолтом, затем снять server_default (как требует SQLite-паттерн проекта)
    op.add_column("levels", sa.Column("max_depth", sa.Integer(), nullable=False, server_default="99"))

    # 2) сид уровней: max_depth = depth_ceiling(strength) (Бог → 16 — дефолт-старт; верх 99 крутится в UI)
    conn = op.get_bind()
    for lid, strength in conn.execute(sa.text("SELECT id, strength FROM levels")).fetchall():
        conn.execute(
            sa.text("UPDATE levels SET max_depth = :d WHERE id = :id"),
            {"d": _depth_ceiling(strength), "id": lid},
        )

    # 3) бэкфилл существующих партий: дописать max_depth в engine-сторону controllers
    #    от ЗАМОРОЖЕННОЙ силы партии (ctl["strength"], уже есть после 5d790f3dfeb5)
    rows = conn.execute(sa.text("SELECT id, controllers FROM games")).fetchall()
    for gid, controllers_json in rows:
        controllers = json.loads(controllers_json) if isinstance(controllers_json, str) else controllers_json
        changed = False
        for ctl in controllers.values():
            if ctl.get("kind") == "engine" and "max_depth" not in ctl:
                ctl["max_depth"] = _depth_ceiling(ctl["strength"])  # Бог → 16 (дефолт-старт)
                changed = True
        if changed:
            conn.execute(
                sa.text("UPDATE games SET controllers = :c WHERE id = :id"),
                {"c": json.dumps(controllers), "id": gid},
            )

    # снять server_default — значение задаётся приложением (snapshot)
    with op.batch_alter_table("levels") as batch:
        batch.alter_column("max_depth", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("levels") as batch:
        batch.drop_column("max_depth")
    # JSON-ключ max_depth в games.controllers оставляем — controller_from_json его игнорирует (.get)
```

- [ ] **Step 4: Тесты миграции — сид уровней и бэкфилл партий (subprocess-стиль, как весь `test_migration.py`; образец — `test_backfill_frozen_engine_config`)**

```python
# backend/tests/unit/test_migration.py — добавить (json/subprocess/create_engine/text уже импортированы в файле)
def test_alembic_seeds_level_max_depth(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    r = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, max_depth FROM levels")).fetchall())
    eng.dispose()
    assert rows["novice"] == 4 and rows["master"] == 15 and rows["god"] == 16  # Бог: дефолт-старт = depth_ceiling(100)


def test_backfill_games_max_depth_from_frozen_strength(tmp_path, monkeypatch):
    """max_depth дописывается в engine-сторону от ЗАМОРОЖЕННОЙ силы партии (не текущей)."""
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    # 1) схема ДО нашей миграции = её down_revision (подставить из Step 2)
    r = subprocess.run(["uv", "run", "alembic", "upgrade", "<DOWN_REVISION>"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # 2) партия со старым engine-ctl (strength есть, max_depth нет)
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    ctl = {
        "black": {"kind": "user", "user_id": 1},
        "white": {"kind": "engine", "level_id": "master", "strength": 90, "timeout_ms": 6000, "nnue": True},
    }
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO users (id, username, password_hash, role, token_epoch) "
                          "VALUES (1, 'alice', 'x', 'user', 0)"))
        conn.execute(text("INSERT INTO games (id, owner_id, controllers, moves, status, undo_count, "
                          "forbidden_log, favorite, finished_at) VALUES "
                          "('g1', 1, :c, '[[7,7]]', 'awaiting_move', 0, '{}', 0, NULL)"),
                     {"c": json.dumps(ctl)})
    eng.dispose()
    # 3) накатить нашу миграцию
    r2 = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    # 4) max_depth = depth_ceiling(90) = 15 (от замороженной силы партии)
    eng2 = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng2.connect() as conn:
        row = conn.execute(text("SELECT controllers FROM games WHERE id='g1'")).fetchone()
    eng2.dispose()
    assert json.loads(row[0])["white"]["max_depth"] == 15
```

- [ ] **Step 5: Обновить фикстуру `_seed_levels` (conftest — «зеркало миграции»; иначе NOT NULL колонка каскадно уронит ВЕСЬ API-сьют через фикстуру `app`)**

```python
# backend/tests/conftest.py — в _seed_levels у каждой строки добавить max_depth = depth_ceiling(strength)
    levels = [
        Level(id="novice", name="Новичок", ordering=0, strength=5, timeout_ms=1000, max_depth=4),
        Level(id="easy", name="Лёгкий", ordering=1, strength=15, timeout_ms=1500, max_depth=6),
        Level(id="low_medium", name="Ниже среднего", ordering=2, strength=35, timeout_ms=2000, max_depth=9),
        Level(id="high_medium", name="Выше среднего", ordering=3, strength=55, timeout_ms=2500, max_depth=11),
        Level(id="hard", name="Сложный", ordering=4, strength=75, timeout_ms=4000, max_depth=13),
        Level(id="master", name="Мастер", ordering=5, strength=90, timeout_ms=6000, max_depth=15),
        Level(id="god", name="Бог", ordering=6, strength=100, timeout_ms=7000, max_depth=16),
    ]
```

- [ ] **Step 6: Применить миграцию и прогнать тесты**

Run: `uv run alembic upgrade head && uv run pytest tests/unit/test_migration.py -q`
Expected: PASS (сид: novice 4, master 15, god 16; бэкфилл партии master → 15).

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/models/level.py alembic/versions/ tests/unit/test_migration.py tests/conftest.py
git commit -m "feat(levels): колонка max_depth + миграция (сид=depth_ceiling, бэкфилл партий от замороженной силы)"
```

---

## Task 4: `Engine.max_depth` (заморозка в партию) + прокидка в `EngineParams`

**Files:**
- Modify: `backend/app/game/controllers.py` (`Engine`, `controller_to_json`, `controller_from_json`)
- Modify: `backend/app/game/players.py` (`make_player`, ~50)
- Modify: `backend/app/routers/games.py` (`create_game`, ~54)
- Test: `backend/tests/unit/test_players.py`, `backend/tests/unit/test_controllers.py`

**Interfaces:**
- Consumes: `Level.max_depth` (Task 3), `EngineParams.max_depth` (Task 2).
- Produces: `Engine(level_id, strength, timeout_ms, nnue, max_depth)`; `controller_to_json` пишет `max_depth`; `controller_from_json` читает `d.get("max_depth", 99)`; `make_player` прокидывает `max_depth=ctl.max_depth` в `EngineParams`.

- [ ] **Step 1: Написать падающие тесты**

```python
# backend/tests/unit/test_controllers.py — добавить
from app.game.controllers import Engine, controller_from_json, controller_to_json


def test_engine_roundtrip_with_max_depth():
    eng = Engine(level_id="novice", strength=5, timeout_ms=1000, nnue=True, max_depth=3)
    assert controller_from_json(controller_to_json(eng)) == eng


def test_controller_from_json_missing_max_depth_defaults_99():
    # старая партия без ключа (недомигрированная) — не падает
    legacy = {"kind": "engine", "level_id": "novice", "strength": 5, "timeout_ms": 1000, "nnue": True}
    eng = controller_from_json(legacy)
    assert eng.max_depth == 99
```

```python
# backend/tests/unit/test_players.py — добавить
# (реальный паттерн файла: адаптер не вызывается в make_player — берётся cast(EngineAdapter, object()))
from typing import cast
from app.domain.engine_params import EngineParams
from app.game.controllers import Engine
from app.game.players import EnginePlayer, make_player
from app.game.ports import EngineAdapter


def test_make_player_passes_max_depth():
    eng = Engine(level_id="easy", strength=15, timeout_ms=1500, nnue=True, max_depth=6)
    player = make_player(eng, cast(EngineAdapter, object()), "g1")
    assert isinstance(player, EnginePlayer)
    assert player._params == EngineParams(strength=15, timeout_turn_ms=1500, max_depth=6)
```

(Существующий `_MASTER = Engine(level_id="master", strength=90, timeout_ms=6000, nnue=True)` в `test_players.py` НЕ сломается — `Engine.max_depth` имеет дефолт 99; `test_controller_roundtrip` через `_MASTER` продолжит работать.)

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `uv run pytest tests/unit/test_controllers.py tests/unit/test_players.py -k max_depth -q`
Expected: FAIL (`TypeError` на `Engine(... max_depth=...)`).

- [ ] **Step 3: Реализация — `controllers.py`**

```python
# backend/app/game/controllers.py
@dataclass(frozen=True)
class Engine:
    level_id: str
    strength: int
    timeout_ms: int
    nnue: bool
    max_depth: int = 99  # глубина поиска, 1..99 (заморожена в партию)


def controller_to_json(c: Controller) -> dict:
    if isinstance(c, Engine):
        return {
            "kind": "engine",
            "level_id": c.level_id,
            "strength": c.strength,
            "timeout_ms": c.timeout_ms,
            "nnue": c.nnue,
            "max_depth": c.max_depth,
        }
    return {"kind": "user", "user_id": c.user_id}


def controller_from_json(d: dict) -> Controller:
    if d["kind"] == "engine":
        return Engine(
            d["level_id"], d["strength"], d["timeout_ms"], d["nnue"], d.get("max_depth", 99)
        )
    return User(d["user_id"])
```

- [ ] **Step 4: Реализация — `players.py` (`make_player`)**

```python
# backend/app/game/players.py — внутри make_player, ветка Engine
    params = EngineParams(
        strength=ctl.strength, timeout_turn_ms=ctl.timeout_ms, max_depth=ctl.max_depth
    )
```

- [ ] **Step 5: Реализация — `routers/games.py` (`create_game`)**

```python
# backend/app/routers/games.py — сборка engine_ctl (~54)
    engine_ctl = Engine(
        level_id=level.id,
        strength=level.strength,
        timeout_ms=level.timeout_ms,
        nnue=nnue,
        max_depth=level.max_depth,
    )
```

- [ ] **Step 6: Запустить тесты**

Run: `uv run pytest tests/unit/test_controllers.py tests/unit/test_players.py -q`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/game/controllers.py app/game/players.py app/routers/games.py tests/
git commit -m "feat(game): заморозка max_depth в Engine-снимок партии + прокидка в EngineParams"
```

---

## Task 5: Эндпоинт `GET/PUT /api/admin/engine-config` — `max_depth` + `depth_ceiling`

**Files:**
- Modify: `backend/app/dtos/engine_config.py` (`LevelConfigDTO`, `LevelUpdate`)
- Modify: `backend/app/routers/admin.py` (`_build_engine_config_dto`)
- Modify: `backend/app/config_repository.py` (`ConfigRepository.update`)
- Test: `backend/tests/unit/test_config_repository.py`, тест роутера (по образцу существующего admin/engine-config теста)

**Interfaces:**
- Consumes: `depth_ceiling` (Task 1), `Level.max_depth` (Task 3).
- Produces: `LevelConfigDTO{id,name,strength,timeout_ms,max_depth,depth_ceiling}`; `LevelUpdate{id,strength,timeout_ms,max_depth}`; `ConfigRepository.update` пишет `level.max_depth`.

- [ ] **Step 1: Написать падающий тест (репозиторий пишет max_depth; GET отдаёт max_depth+depth_ceiling)**

```python
# backend/tests/unit/test_config_repository.py — добавить
# (реальный паттерн файла: фикстура `session` + ручной `await _seed_levels(session)`)
import pytest
from app.config_repository import ConfigRepository
from app.dtos.engine_config import LevelUpdate


@pytest.mark.asyncio
async def test_update_writes_max_depth(session):
    from tests.conftest import _seed_levels

    await _seed_levels(session)
    repo = ConfigRepository(session)
    await repo.update([LevelUpdate(id="novice", strength=5, timeout_ms=1000, max_depth=2)], nnue=True)
    await session.commit()
    lv = await repo.get_level("novice")
    assert lv.max_depth == 2
```

```python
# backend/tests/api/test_admin_engine_config.py — добавить (паттерн файла: фикстуры app, client + локальный _login_admin)
async def test_get_engine_config_returns_max_depth_and_ceiling(app, client):
    await _login_admin(app, client)
    levels = (await client.get("/api/admin/engine-config")).json()["levels"]
    novice = next(l for l in levels if l["id"] == "novice")
    assert novice["max_depth"] == 4          # сид = depth_ceiling(5)
    assert novice["depth_ceiling"] == 4
    god = next(l for l in levels if l["id"] == "god")
    assert god["depth_ceiling"] == 16        # depth_ceiling(100)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `uv run pytest tests/unit/test_config_repository.py -k max_depth -q`
Expected: FAIL (`LevelUpdate` без `max_depth` / нет поля в DTO).

- [ ] **Step 3: Реализация — DTO**

```python
# backend/app/dtos/engine_config.py
class LevelConfigDTO(BaseModel):
    id: str
    name: str
    strength: int
    timeout_ms: int
    max_depth: int
    depth_ceiling: int  # потолок от силы (бэк считает; фронт строит диапазон, формулу не дублирует в данных)


class LevelUpdate(BaseModel):
    id: str
    strength: int = Field(ge=0, le=100)
    timeout_ms: int = Field(ge=200, le=30000)
    max_depth: int = Field(ge=1, le=99)  # санитизация типа/границ движка (не диапазонный гард — диапазон на фронте)
```

- [ ] **Step 4: Реализация — `admin.py` (`_build_engine_config_dto`)**

```python
# backend/app/routers/admin.py
from ..domain.levels_depth import depth_ceiling

def _build_engine_config_dto(levels: list, nnue: bool) -> EngineConfigDTO:
    return EngineConfigDTO(
        levels=[
            LevelConfigDTO(
                id=lv.id, name=lv.name, strength=lv.strength, timeout_ms=lv.timeout_ms,
                max_depth=lv.max_depth, depth_ceiling=depth_ceiling(lv.strength),
            )
            for lv in levels
        ],
        nnue=nnue,
    )
```

- [ ] **Step 5: Реализация — `config_repository.py` (`update`)**

```python
# backend/app/config_repository.py — в цикле мутации
        for lu in level_updates:
            level = level_map[lu.id]
            level.strength = lu.strength
            level.timeout_ms = lu.timeout_ms
            level.max_depth = lu.max_depth
```

- [ ] **Step 6: Обновить существующие PUT-тесты `tests/api/test_admin_engine_config.py` (max_depth теперь обязателен в `LevelUpdate` → старые PUT без него дадут 422)**

В каждый непустой `levels`-элемент существующих PUT-тестов добавить `max_depth`:
- `test_put_engine_config_updates`: novice → `"max_depth": 4`, god → `"max_depth": 16`.
- `test_put_atomicity_unknown_id_rolls_back_valid`: валидному novice → `"max_depth": 4`.
- `test_put_invalid_strength_422`, `test_put_invalid_strength_negative_422`, `test_put_invalid_timeout_too_low_422`, `test_put_invalid_timeout_too_high_422`: добавить валидный `"max_depth": 4`, чтобы 422 был ИМЕННО по проверяемому полю, а не по отсутствию max_depth.
- БЕЗ изменений: `test_put_empty_levels_changes_only_nnue` (пустой список), `*_non_admin_403`, `test_put_unknown_level_id_422` (нет валидного уровня), `test_get_engine_config_admin` (`set(keys) >= {...}` — подмножество, проходит).

- [ ] **Step 7: Запустить тесты эндпоинта/репозитория**

Run: `uv run pytest tests/unit/test_config_repository.py tests/api/test_admin_engine_config.py -q`
Expected: PASS.

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check app tests && uv run ruff format app tests
git add app/dtos/engine_config.py app/routers/admin.py app/config_repository.py tests/
git commit -m "feat(admin): max_depth + depth_ceiling в GET/PUT engine-config"
```

---

## Task 6: Живой движок — рез глубины подтверждён через реестр (holds-line)

**Files:**
- Test: `backend/tests/integration/test_registry_live.py` (добавить кейс)

**Interfaces:**
- Consumes: `EngineParams.max_depth` (Task 2), реестр (`compute_move`).

Назначение: проверить, что партия с заданным `max_depth` через `EngineRegistry` не ломается (процесс жив, ход легален). Сам факт «доставка режет глубину» проверяется raw-прогоном (`probe … check`, Task 1 Step 5) — через реестр достигнутую глубину не прочитать (`_read_until` ест realtime-строки).

- [ ] **Step 1: Написать тест (по образцу holds-line в файле)**

```python
# backend/tests/integration/test_registry_live.py — добавить
# (реальный паттерн файла: фикстура rapfi_paths + локальный хелпер _reg(rapfi_paths) + try/finally close;
#  BOARD_SIZE уже импортирован в файле; P-стиль EngineParams тоже там есть)
async def test_compute_move_with_max_depth_returns_legal_move(rapfi_paths):
    reg = _reg(rapfi_paths)
    try:
        params = EngineParams(strength=100, timeout_turn_ms=2000, max_depth=2)
        moves = [(7, 7), (7, 8), (8, 8), (6, 8)]  # позиция, ход чёрных
        mv = await reg.compute_move("g-depth", moves, params, level_tag="test")
        assert mv not in {tuple(m) for m in moves}
        assert 0 <= mv[0] < BOARD_SIZE and 0 <= mv[1] < BOARD_SIZE
    finally:
        await reg.close()
```

- [ ] **Step 2: Запустить — убедиться, что проходит (механизм уже реализован в Task 2)**

Run: `uv run pytest tests/integration/test_registry_live.py -k max_depth -q`
Expected: PASS (движок отвечает легальным ходом под `INFO max_depth 2`).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_registry_live.py
git commit -m "test(registry): партия с max_depth даёт легальный ход (live)"
```

---

## Task 7: Фронт — столбец «Глубина», зажим силы, диапазоны

**Files:**
- Modify: `frontend/src/admin/admin.api.ts` (типы `LevelConfigDTO`, `EngineConfigUpdate`)
- Modify: `frontend/src/admin/EngineTab.tsx`
- Create: `frontend/src/admin/levelDepth.ts` (формула + правила диапазона/зажима, чистые функции)
- Test: `frontend/src/admin/levelDepth.test.ts`, `frontend/src/admin/EngineTab.test.tsx` (добавить кейсы)

**Interfaces:**
- Consumes: `GET` отдаёт `max_depth`, `depth_ceiling` на уровень.
- Produces: столбец глубины с диапазоном `[нижняя…верхняя]`, зажим силы, подстановка на верх при выходе.

**Решение по дублированию формулы:** `depthCeiling(strength)` дублируется на фронте (статичная константа движка, не наша дрейфующая логика) — нужна для ЖИВОГО пересчёта потолка при правке силы (до сохранения). Unit-тест сверяет фронт-значения с бэк-таблицей ступеней (фиксирует, что копия не разъехалась). Это деталь реализации, не нарушает «один источник» (источник — движок; обе копии заперты тестом).

- [ ] **Step 1: Написать падающий тест чистых функций**

```typescript
// frontend/src/admin/levelDepth.test.ts
import { describe, it, expect } from "vitest";
import { depthCeiling, depthRange, clampStrength } from "./levelDepth";

describe("depthCeiling — копия формулы движка, сверка с бэк-таблицей", () => {
  const table: [number, number][] = [
    [0, 4], [5, 4], [6, 4], [7, 5], [12, 5], [13, 6], [15, 6], [19, 6],
    [20, 7], [26, 7], [27, 8], [33, 8], [34, 9], [41, 9], [42, 10], [49, 10],
    [50, 11], [58, 11], [59, 12], [67, 12], [68, 13], [77, 13], [78, 14],
    [88, 14], [89, 15], [99, 15], [100, 16],
  ];
  it.each(table)("s=%i → %i", (s, d) => expect(depthCeiling(s)).toBe(d));
});

describe("depthRange — [нижняя…верхняя], нижняя=верх предыдущего, Бог особый", () => {
  // strengths по порядку уровней (слабый→сильный)
  it("Новичок: [1 … 4]", () => expect(depthRange(0, [5, 15])).toEqual([1, 4]));
  it("средний уровень: [верх пред … потолок]", () =>
    expect(depthRange(1, [5, 15, 35])).toEqual([4, 6])); // лёгкий s15: нижняя=ceil(5)=4, верх=ceil(15)=6
  it("Бог (последний, сила 100): [16 … 99]", () =>
    expect(depthRange(6, [5, 15, 35, 55, 75, 90, 100])).toEqual([16, 99]));
});

describe("clampStrength — зажим силы соседями", () => {
  it("Новичок снизу 1", () => expect(clampStrength(0, 0, [5, 15])).toBe(1));     // не ниже 1
  it("средний: [сила пред … сила след − 1]", () =>
    expect(clampStrength(1, 2, [5, 15, 35])).toBe(5));   // лёгкий: ниже новичка(5) → 5
  it("Бог сверху 100", () => expect(clampStrength(6, 150, [5, 15, 35, 55, 75, 90, 100])).toBe(100));
});
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run (из `frontend/`): `npx vitest run src/admin/levelDepth.test.ts`
Expected: FAIL (модуль не существует).

- [ ] **Step 3: Реализация — `levelDepth.ts`**

```typescript
// frontend/src/admin/levelDepth.ts
// Копия формулы движка Rapfi (skill.h) для ЖИВОГО пересчёта в UI. Сверяется с
// бэк-таблицей unit-тестом (levelDepth.test.ts) — не дрейфует. Источник истины — движок.
const GOD_STRENGTH = 100;
const MAX_SEARCH_DEPTH = 99; // engine/config.toml max_search_depth

export function depthCeiling(strength: number): number {
  return 4 + Math.floor(24 * (1 - Math.pow(0.5, strength / 100)));
}

/** Диапазон [нижняя, верхняя] глубины для уровня index в списке сил strengths (по порядку). */
export function depthRange(index: number, strengths: number[]): [number, number] {
  const strength = strengths[index];
  if (strength >= GOD_STRENGTH) return [depthCeiling(GOD_STRENGTH), MAX_SEARCH_DEPTH]; // Бог [16…99]
  const lower = index === 0 ? 1 : depthCeiling(strengths[index - 1]);
  return [lower, depthCeiling(strength)];
}

/** Зажим силы соседями: [сила предыдущего … сила следующего − 1]; первый снизу 1, последний сверху 100. */
export function clampStrength(index: number, value: number, strengths: number[]): number {
  const lo = index === 0 ? 1 : strengths[index - 1];
  const hi = index === strengths.length - 1 ? 100 : strengths[index + 1] - 1;
  return Math.min(Math.max(value, lo), hi);
}
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `npx vitest run src/admin/levelDepth.test.ts`
Expected: PASS.

- [ ] **Step 5: Расширить типы API**

```typescript
// frontend/src/admin/admin.api.ts
export type LevelConfigDTO = {
  id: string; name: string; strength: number; timeout_ms: number;
  max_depth: number; depth_ceiling: number;
};
export type EngineConfigUpdate = {
  levels: { id: string; strength: number; timeout_ms: number; max_depth: number }[];
  nnue: boolean;
};
```

**Также обновить `frontend/src/admin/admin.api.test.ts`** (иначе `tsc --noEmit` в финале упадёт на типизированном аргументе `putEngineConfig`):
- стр.21 `putEngineConfig({ levels: [{ id: "novice", strength: 9, timeout_ms: 2000 }], nnue: false })` → добавить `max_depth: 5` в элемент `levels`.
- стр.22 `expect(body).toEqual({ levels: [{ id: "novice", strength: 9, timeout_ms: 2000 }], nnue: false })` → добавить `max_depth: 5` в ожидаемый `levels`-элемент.
- GET-mock (стр.6-7) и put-response-mock (стр.19): `HttpResponse.json` принимает любой объект — `tsc` не ломают; для реализма можно добавить `max_depth`/`depth_ceiling`, но не обязательно.

- [ ] **Step 6: Обновить существующий тест + добавить тест столбца/подстановки**

Сначала — **обновить существующий** `EngineTab.test.tsx` (иначе сломается): `CFG` без `max_depth`/`depth_ceiling`, а тест «правка+сохранить шлёт мс» проверяет точный `body.levels[0]).toEqual({id,strength,timeout_ms})` — после добавления `max_depth` в save `toEqual` не сойдётся.

```tsx
// CFG → добавить max_depth/depth_ceiling
const CFG = { levels: [{ id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000, max_depth: 4, depth_ceiling: 4 }], nnue: true };

// в тесте "правка+сохранить шлёт мс": после ввода силы 9 (единственная строка) ожидаемый body.levels[0]:
expect((body as { levels: { id: string; strength: number; timeout_ms: number; max_depth: number }[] }).levels[0])
  .toEqual({ id: "novice", strength: 9, timeout_ms: 1000, max_depth: 4 });
// depth 4 ≤ потолок depthCeiling(9)=5 → не режется; timeout 1.0с → 1000мс (конвертация сохранена)
```

Затем — **новый тест подстановки** (с реальным телом; детали userEvent при необходимости подогнать под controlled-input):

```tsx
it("при падении потолка глубина встаёт на верхнюю границу", async () => {
  const cfg = { levels: [
    { id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000, max_depth: 4, depth_ceiling: 4 },
    { id: "easy", name: "Лёгкий", strength: 15, timeout_ms: 1500, max_depth: 6, depth_ceiling: 6 },
  ], nnue: true };
  server.use(http.get("/api/admin/engine-config", () => HttpResponse.json(cfg)));
  render(<EngineTab />);
  const easyDepth = await screen.findByLabelText("Лёгкий глубина");
  expect(easyDepth).toHaveValue(6);
  // уронить силу easy до 7 → потолок depthCeiling(7)=5 → depth 6 за пределом → встаёт на 5
  const easyStrength = screen.getByLabelText(/Лёгкий.*сила/i);
  await userEvent.clear(easyStrength);
  await userEvent.type(easyStrength, "7");
  expect(easyDepth).toHaveValue(5);
});
```

- [ ] **Step 7: Реализация — `EngineTab.tsx`**

Изменения (по месту):
- `Row` (сейчас `{id,name,strength,timeoutSec}`) += `depth: number`. Load-маппинг (в `useEffect` и в ответе `save`): `depth: l.max_depth` рядом с существующим `timeoutSec: l.timeout_ms / 1000`. **`timeoutSec` НЕ трогаем.**
- При рендере держать массив сил по порядку (`rows.map(r => r.strength)`) для `depthRange`/`clampStrength`.
- Столбец «Глубина» в `<thead>`/`<tbody>`: `<input type="number">` с `min`/`max` из `depthRange(i, strengths)`, `aria-label={`${r.name} глубина`}`, подпись «макс N» (верх диапазона; у Бога «макс 99»).
- В `setRow` при изменении `strength`: пересчитать `clampStrength`, затем для строки пересчитать `depthRange`; если текущая `depth` вышла за верх — поставить верх.
- `save`: `levels: rows.map(r => ({ id: r.id, strength: r.strength, timeout_ms: Math.round(r.timeoutSec * 1000), max_depth: r.depth }))` — **сохранить конвертацию `timeoutSec`→мс** (как сейчас); `r.timeout_ms` НЕ существует.

```tsx
// фрагмент: ячейка глубины в строке i
const strengths = rows.map((x) => x.strength);
const [lo, hi] = depthRange(i, strengths);
// ...
<td>
  <input
    type="number"
    min={lo}
    max={hi}
    aria-label={`${r.name} глубина`}
    value={r.depth}
    onChange={(e) => setRow(r.id, { depth: Math.min(Math.max(Number(e.target.value), lo), hi) })}
  />
  <span className={styles.desc}>макс {hi}</span>
</td>
```

```tsx
// setRow: при смене силы — зажать силу и подставить глубину на верх, если вышла
const setRow = (id: string, patch: Partial<Row>) => {
  setSaved(false);
  setRows((rs) => {
    const idx = rs!.findIndex((r) => r.id === id);
    let next = rs!.map((r) => (r.id === id ? { ...r, ...patch } : r));
    if (patch.strength !== undefined) {
      const strengths = next.map((r) => r.strength);
      const clamped = clampStrength(idx, patch.strength, strengths);
      strengths[idx] = clamped;
      const [, hi] = depthRange(idx, strengths);
      next = next.map((r, k) =>
        k === idx ? { ...r, strength: clamped, depth: Math.min(r.depth, hi) } : r,
      );
    }
    return next;
  });
};
```

- [ ] **Step 8: Запустить фронт-тесты**

Run (из `frontend/`): `npx vitest run src/admin/`
Expected: PASS (levelDepth + EngineTab + admin.api).

- [ ] **Step 9: Сборка (проверка типов) + commit**

```bash
cd frontend && npx tsc --noEmit && npx vitest run src/admin/
git add frontend/src/admin/
git commit -m "feat(admin-ui): столбец глубины уровня — диапазон от силы, зажим силы, подстановка"
```

---

## Финальная проверка (после всех задач)

- [ ] Бэк целиком: `cd backend && uv run pytest -q` — всё зелёное (unit + integration, последовательно).
- [ ] Фронт целиком: `cd frontend && npx tsc --noEmit && npx vitest run`.
- [ ] Ручная проверка (Alexey): открыть админку → Движок, покрутить силу/глубину уровня, создать партию, сыграть — движок реально слабее на малой глубине.
