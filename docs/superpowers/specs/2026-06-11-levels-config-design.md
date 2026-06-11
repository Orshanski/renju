# Уровни сложности в конфиге — дизайн

- **Дата:** 2026-06-11
- **Статус:** черновик на ревью
- **bd:** rj-0zz (поглощает rj-jkr «новая шкала»; связано с rj-tan «admin-UI»)
- **Дополняет:** основную спеку §4.5 (уровни сложности)

## Проблема

Сейчас уровни захардкожены в `app/domain/levels.py`: `Level(StrEnum)` фиксирует
**количество и имена**, `LEVELS: dict` — **числа** strength/timeout. Любое
изменение (откалибровать число, переименовать, добавить/убрать уровень) = правка
кода + теста + коммит.

Уровни — это **метаданные**, по которым строится процесс (имена, числовые
значения, само их количество). Им место в данных, не в коде. Тогда калибровка
идёт без правки кода, а в перспективе пользователь может задать свой набор (хоть
100 уровней) через будущий admin-редактор.

## Решение

### Файл `backend/levels.toml`

Упорядоченный список записей; **порядок в файле = порядок уровней** (от слабого к
сильному). Каждая запись:

```toml
[[levels]]
id = "novice"            # стабильный строковый id (хранится в партии, шлёт клиент)
name = "Новичок"         # человекочитаемое имя (для селектора / GET /levels)
strength = 5             # INFO strength, 0..100
timeout_turn_ms = 1000   # INFO timeout_turn
```

Стартовый набор — текущая 7-ступенчатая шкала:
`novice 5 · easy 15 · low_medium 35 · high_medium 55 · hard 75 · master 90 · god 100`
(имена — на усмотрение; `timeout_turn_ms` растёт со сложностью, как сейчас).

### Код

- **Переименовать** `app/domain/levels.py` → `app/domain/engine_params.py`. После
  выноса уровней в данные модуль содержит только `EngineParams` (`strength`,
  `timeout_turn_ms`) — тип параметров движка (структура, не значения); им
  пользуется адаптер (`compute_move(..., params: EngineParams)`) и
  `protocol.init_commands`. Имя `engine_params` честнее, чем `levels` без уровней (B2).
  - **Удалить** из него `Level(StrEnum)` и `LEVELS: dict`.
  - Переименование тянет обновление импорта `EngineParams` у текущих потребителей
    (B7): `app/rapfi/protocol.py`, `app/rapfi/adapter.py`, `tests/unit/test_protocol.py`,
    `tests/integration/test_adapter.py` — путь `app.domain.levels` → `app.domain.engine_params`.
- **Новый config-слой `app/levels_config.py`** (I/O — чтение файла, поэтому НЕ
  домен, §4.9):
  - `LevelInfo` — запись уровня: `id: str`, `name: str`, `params: EngineParams`.
  - `load_levels(path) -> list[LevelInfo]` — читает+парсит TOML; для каждой записи
    **собирает `EngineParams(strength=rec["strength"], timeout_turn_ms=rec["timeout_turn_ms"])`
    из плоских полей** и оборачивает в `LevelInfo(id, name, params)` (B3); возвращает
    упорядоченный список. **Пустой набор (ни одной `[[levels]]`) → `ValueError`**, а
    не молчаливый `[]` (B5).
  - `resolve_level(levels, level_id) -> LevelInfo | None` — резолв по id (нет →
    None; вызывающий решает: в HTTP → 422, в CLI → явная ошибка, B6).
  - Путь файла — из `Settings` (`app/config.py`), env `RENJU_LEVELS_FILE`, дефолт
    `REPO_ROOT / "backend" / "levels.toml"` (`REPO_ROOT` = корень репо) (B9).

### Когда читается (lifecycle)

- Конфиг читается **при старте партии**, не на каждый ход. При создании партии:
  `level_id` → `load_levels` → `resolve_level` → `EngineParams` → **фиксируются на
  партию**; все ходы партии используют эти params.
- **Перезагрузка после правок — бесплатна:** каждая новая партия читает свежий
  файл, поэтому поправил `levels.toml` → следующая новая игра уже с новыми
  числами, без рестарта. Идущая партия доигрывается на своих params — это норма.
- Текущий этап (нет HTTP/БД): в `play_cli` файл читается один раз в `main()` (до
  парсинга `--level`, чтобы дать argparse `choices`/`default` и зарезолвить id);
  `game_loop` получает уже готовый `LevelInfo` и работает с его `params` (B4).
  Будущее (этап 3): `POST /games` валидирует `level_id` и фиксирует params.

### Валидация

- **Сейчас:** базовый парс TOML (синтаксис) + одна lifecycle-проверка — **набор
  непустой** (пустой → `ValueError`, иначе `play_cli` упадёт на `levels[0]`, B5).
  Прочих инвариант-проверок нет — файл правится руками. Битый TOML упадёт при
  чтении естественно.
- **Инварианты — на будущее** (когда появится admin-редактор с фронтом, rj-tan;
  там валидатор и решит проблему — UI не даст ввести мусор): `strength ∈ 0..100`,
  `timeout_turn_ms > 0`, `id` уникальны и непусты, `name` непуст, набор непустой,
  `strength` монотонно неубывает по порядку. **Максимум (== 100) НЕ требуется.**
- Резолв несуществующего `level_id` → `None` (в HTTP-слое будущего → 422).

### play_cli (адаптация под текущий этап)

- Убрать `from app.domain.levels import LEVELS, Level`; брать уровни из
  `app.levels_config.load_levels` (`EngineParams` при нужде — из
  `app.domain.engine_params`).
- В `main()`: `levels = load_levels(...)` **до** `argparse`; `--level` choices —
  из `[lv.id for lv in levels]`, дефолт — `levels[0].id` (набор гарантированно
  непуст — `load_levels` бросил бы `ValueError` на пустом, B5). `main()` резолвит
  выбранный id и передаёт `LevelInfo` в `game_loop` (B4). Choices ограничивают ввод
  валидными id, поэтому `resolve_level` тут не вернёт `None`; на всякий — явный
  `raise` при `None` (B6).
- `game_loop(level: LevelInfo)`: `params = level.params`; печать «Уровень: {level.name}».

## Что НЕ в этом этапе (scope — за рамками, не предлагать как findings)

- **Admin-UI редактор уровней и его валидатор** (rj-tan) — будущее, с фронтом.
- **HTTP `POST /games`, `GET /levels`** (этапы 2–3) — здесь только домен/config +
  `play_cli`. Контракт `GET /levels` (отдаёт `id`+`name`) лишь упомянут.
- **БД-хранение `levelId` партии** — этап 2.
- **mtime-кэш / reload во время идущей партии** — сознательно убрано (читаем на
  старте партии).
- **Инвариант-валидация файла** — отложена в будущий admin-валидатор.
- Дебют (§4.10), прочие доменные модули — не трогаем.

## Затронутый код

- **Переименовать** `app/domain/levels.py` → `app/domain/engine_params.py` (убрать
  `Level`/`LEVELS`; оставить `EngineParams`).
- **Создать:** `backend/levels.toml`; `app/levels_config.py` (`LevelInfo`,
  `load_levels`, `resolve_level`); поле пути `levels_file` в `Settings` (`app/config.py`).
- **Обновить импорт `EngineParams`** (`app.domain.levels` → `app.domain.engine_params`):
  `app/rapfi/protocol.py`, `app/rapfi/adapter.py`, `tests/unit/test_protocol.py`,
  `tests/integration/test_adapter.py` (B7).
- **`tests/integration/test_adapter.py`** (B1): помимо импорта — убрать `LEVELS`/`Level`,
  заменить `LEVELS[Level.NOVICE]` в `test_real_levels_work_end_to_end` на локальный
  `EngineParams(...)` (как уже сделано для `FAST` на стр. 10).
- **`backend/scripts/play_cli.py`** — уровни из конфига (см. секцию play_cli).
- **`tests/unit/test_levels.py`** → переписать под config-слой (можно переименовать в
  `test_levels_config.py`): на **временной TOML-фикстуре** (`tmp_path`/inline)
  проверять `load_levels` (парс структуры, плоское→`EngineParams`), `resolve_level`
  (hit + miss→`None`), `ValueError` на пустом наборе. **Инвариант-тесты
  (`test_strength_in_engine_range_and_monotonic`, `test_timeouts_positive`,
  `test_all_levels_have_params`) удаляются** вместе с enum — инварианты отложены в
  будущий admin-валидатор (B8). **`test_params_immutable`** (проверяет frozen-ность
  `EngineParams` через `LEVELS[Level.NOVICE]`) — НЕ удалять, а переписать на
  локальный `EngineParams(...)` (проверка типа полезна и без `LEVELS`) и положить
  рядом с типом (тест для `engine_params`) (N1).
- **Синхронизировать** основную спеку §4.5 (уровни — данные в файле, `Level` enum
  убран, `levelId` — строка-id из набора).

## Открытый вопрос

- TOML-парсинг: Python 3.11+ имеет `tomllib` в stdlib (чтение) — зависимостей не
  добавляем. Запись (для будущего UI) — отдельная история.
