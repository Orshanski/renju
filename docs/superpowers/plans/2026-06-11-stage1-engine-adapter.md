# Renju · Этап 1/4 — Каркас бэкенда + домен + адаптер Rapfi · План реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Работающий Python-каркас бэкенда: чистая доменная логика рэндзю (статусы, исходы, undo, уровни), адаптер движка Rapfi (процесс, протокол, парсинг, перезапуск), оформленный `engine/` (submodule + config + build.sh + runbook) и консольная игра `play_cli.py` для ручной проверки.

**Architecture:** Слоистый бэкенд (спек §4.9): `app/domain/` — чистая логика без I/O; `app/rapfi/` — инфраструктурный адаптер движка (pure-протокол отделён от процесса); `app/config.py` — настройки. HTTP/БД на этом этапе нет — они в этапах 2–3. Тесты двух сортов: юнит (домен, протокол) и интеграционные против реального бинаря `pbrain-rapfi`.

**Tech Stack:** Python 3.13, uv, pydantic-settings, pytest + pytest-asyncio, ruff. Движок: Rapfi (C++, уже собран: `engine/rapfi/Rapfi/build/mac-arm64-NEON-DOTPROD/pbrain-rapfi`), NNUE-веса mix9svq из `rapfi-networks`.

**Контекст для исполнителя (всё проверено живыми прогонами 2026-06-11):**

- Работаем в feature-ветке `stage1-engine-adapter` (создать от `main` первым действием); в `main` — только мёрж принятого этапа. Напрямую в `main` не коммитим.
- Протокол Piskvork/yx поверх stdin/stdout, текстовый:
  - `START 15` → ответ `OK`. Повторный `START 15` в той же сессии **работает** (переинициализация без перезапуска процесса).
  - `INFO rule 4` (рэндзю), `INFO strength N` (0–100), `INFO timeout_turn N` (мс) — без ответа.
  - Запрос хода: `BOARD` + строки `x,y,who` + `DONE` → движок печатает шумовые строки `MESSAGE …` и затем голую строку хода `x,y` (например `5,4`). Пустая позиция: команда `BEGIN` (движок ходит первым).
  - `who` — относительно стороны, которая сейчас ходит: `1` = камень того, кто ходит, `2` = соперник. Камни передаются **в порядке ходов**, первый камень — чёрный.
  - Фолы: `YXBOARD` + строки `x,y,who` + `DONE` (доска ставится БЕЗ запуска расчёта) → `YXSHOWFORBID` → ответ одной строкой `FORBID 0707.` — конкатенация пар `%02d%02d` в порядке **cx, cy** (x первым; подтверждено исходником `gomocup.cpp::showForbid`), завершается точкой. Пустой список: `FORBID .`. Список непуст только когда ход чёрных (чётное число камней).
  - Ошибки: `ERROR <текст>` (например `ERROR Unknown command: FOOBAR`).
  - `ABOUT` → строка `name="Rapfi", version="0.43.02 …"…`. `END` — завершение процесса.
  - Шум, который надо игнорировать при чтении: строки с префиксами `MESSAGE`, `DEBUG`, `INFO`, а также `OK`. MESSAGE-строки приходят и **до** `OK` (загрузка конфига/весов).
- NNUE: бинарь запускается `pbrain-rapfi --config engine/config.toml` (cwd = корень репо). `engine/config.toml` уже создан и проверен (веса `mix9svqrenju_bs15_black/white.bin.lz4` грузятся, в выводе `MESSAGE mix9svq nnue: weight loaded`). Пути весов в конфиге резолвятся относительно каталога конфига.
- Веса: submodule `Networks` внутри rapfi уже инициализирован (`git -C engine/rapfi submodule update --init Networks`).
- Клон rapfi: `https://github.com/dhbloo/rapfi.git`, HEAD `3aedf3a2ab0ab710a9f3d00e57d5287ceb864894`, чистый.
- uv 0.10.10 и Python 3.13.9 установлены.

---

## Карта файлов этапа

```
backend/
  pyproject.toml               # проект uv: deps, pytest, ruff
  app/
    __init__.py
    config.py                  # Settings: пути к бинарю/конфигу Rapfi
    domain/
      __init__.py
      values.py                # Point, Color, GameStatus, исключения
      rules.py                 # исходы: пятёрка/оверлайн белых/ничья
      game.py                  # валидация хода человека, усечение undo
      undo.py                  # undo-политика (можно/лимит/после конца)
      levels.py                # Level → EngineParams (strength, timeout)
    rapfi/
      __init__.py
      protocol.py              # PURE: сборка команд + парсинг строк
      process.py               # OS-процесс: spawn/чтение/запись/убийство
      adapter.py               # фасад: compute_move / forbidden_points
  tests/
    conftest.py
    unit/
      test_sanity.py
      test_values.py
      test_rules.py
      test_game.py
      test_undo.py
      test_levels.py
      test_protocol.py
      test_config.py
    integration/
      fixtures/hang_engine.sh  # заглушка «зависший движок»
      test_process.py
      test_adapter.py
  scripts/
    play_cli.py                # консольная партия с движком (ручной smoke)
engine/
  config.toml                  # УЖЕ СОЗДАН — закоммитить
  build.sh                     # пересборка Rapfi под CPU хоста
  RUNBOOK.md                   # как развернуть движок с нуля (clone + pin + build)
# .gitignore НЕ трогаем: engine/rapfi/ (чужой GPL-код) остаётся вне git
```

---

### Task 1: Каркас backend-проекта (uv + pytest)

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/tests/conftest.py` (пустой пока)
- Create: `backend/tests/unit/test_sanity.py`

- [ ] **Step 1: Создать `backend/pyproject.toml`**

```toml
[project]
name = "renju-backend"
version = "0.1.0"
description = "Renju web app backend"
requires-python = ">=3.13"
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.2",
]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.24",
    "ruff>=0.4",
]

[tool.uv]
# Виртуальный проект: само приложение как пакет не собираем и не ставим,
# uv управляет только зависимостями. Импорты работают через pytest pythonpath.
package = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]  # чтобы `import app` / `import scripts` работали из тестов

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Создать пакеты и smoke-тест**

`backend/app/__init__.py` — пустой файл.
`backend/tests/conftest.py` — пока пустой файл (наполнится в Task 11).
`backend/tests/unit/test_sanity.py`:

```python
def test_sanity():
    assert True
```

- [ ] **Step 3: Установить окружение и прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv sync`
Expected: создан `.venv`, lock-файл `uv.lock`.

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest -v`
Expected: `1 passed`.

- [ ] **Step 4: Commit**

```bash
git -C /Users/alexey/code/Renju add backend
git -C /Users/alexey/code/Renju commit -m "feat(backend): scaffold uv project with pytest"
```

(Примечание: `uv.lock` коммитим — воспроизводимость окружения.)

---

### Task 2: Оформление `engine/` — config, build.sh, runbook (движок остаётся ВНЕ git)

Rapfi — чужой GPL-код, в git проекта не вносится ни в каком виде (это решение уже зафиксировано в `.gitignore` строкой `/engine/rapfi/` — её НЕ трогаем). В git идут только наши три файла: `engine/config.toml`, `engine/build.sh`, `engine/RUNBOOK.md`. Воспроизводимость даёт runbook: URL + зафиксированный коммит + сборка на целевом хосте (как и предписывает спек §6: подготовка хоста — инструкцией-runbook).

**Files:**
- Commit existing: `engine/config.toml` (уже создан и проверен)
- Create: `engine/build.sh`
- Create: `engine/RUNBOOK.md`

- [ ] **Step 1: Создать `engine/build.sh`**

```bash
#!/usr/bin/env bash
# Сборка Rapfi из engine/rapfi под CPU текущей машины.
# SIMD-расширения (NEON/DOTPROD/AVX2/…) CMakeLists определяет сам.
# ВАЖНО: бинарь НЕ переносим между разными CPU — на каждом хосте своя сборка (иначе SIGILL).
set -euo pipefail
cd "$(dirname "$0")/rapfi/Rapfi"
cmake -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native -j
echo "OK: $(pwd)/build/native/pbrain-rapfi"
```

Run: `chmod +x /Users/alexey/code/Renju/engine/build.sh`

(Запускать сборку сейчас не нужно — рабочий бинарь уже есть в `build/mac-arm64-NEON-DOTPROD/`; скрипт понадобится на новых хостах и проверяется runbook'ом.)

- [ ] **Step 2: Создать `engine/RUNBOOK.md`**

```markdown
# Rapfi — развёртывание движка с нуля

Движок собирается НА ЦЕЛЕВОМ ХОСТЕ под его CPU. Перенос готового бинаря
между разными CPU ломается на нелегальных инструкциях (SIGILL).

## Шаги

1. Получить исходники (каталог `engine/rapfi` гитигнорится — это локальный
   клон, в git проекта он не входит; пин — проверенный коммит):

       git clone https://github.com/dhbloo/rapfi.git engine/rapfi
       git -C engine/rapfi checkout 3aedf3a2ab0ab710a9f3d00e57d5287ceb864894
       git -C engine/rapfi submodule update --init Networks   # NNUE-веса (~50 МБ)

2. Собрать (нужны cmake и компилятор C++17: Apple clang / gcc):

       engine/build.sh

   Бинарь: `engine/rapfi/Rapfi/build/native/pbrain-rapfi`.
   SIMD-флаги CMake выбирает автоматически под CPU хоста.

3. Smoke-проверка (из корня репо; ожидается ход вида `x,y` последней строкой,
   в MESSAGE-строках — `mix9svq nnue: weight loaded`):

       printf 'START 15\nINFO rule 4\nINFO timeout_turn 2000\nBOARD\n7,7,2\nDONE\nEND\n' \
         | engine/rapfi/Rapfi/build/native/pbrain-rapfi --config engine/config.toml

## Конфиг

`engine/config.toml` — скопирован из `Networks/config-example/config.toml`,
пути весов исправлены на `rapfi/Networks/...` (резолвятся относительно каталога
конфига). Эвалюатор: `mix9svq`, рэндзю-веса парой black/white. Важные
зафиксированные значения: `coord_conversion_mode = "none"` (координаты x,y
как в протоколе, без конверсий — на это рассчитан парсер адаптера) и
`default_thread_num = 1`.

## Как бэкенд находит бинарь

`app/config.py`: env `RENJU_RAPFI_BIN`, иначе самый свежий по mtime
`engine/rapfi/Rapfi/build/*/pbrain-rapfi`. Конфиг: env `RENJU_RAPFI_CONFIG`,
иначе `engine/config.toml`.
```

- [ ] **Step 3: Commit**

```bash
git -C /Users/alexey/code/Renju add engine/config.toml engine/build.sh engine/RUNBOOK.md
git -C /Users/alexey/code/Renju commit -m "feat(engine): NNUE config + build script + engine runbook"
```

Run: `git -C /Users/alexey/code/Renju status --porcelain`
Expected: строк `engine/…` нет (движок остался под gitignore).

---

### Task 3: Домен — базовые типы (`values.py`)

**Files:**
- Create: `backend/app/domain/__init__.py` (пустой)
- Create: `backend/app/domain/values.py`
- Test: `backend/tests/unit/test_values.py`

- [ ] **Step 1: Написать падающий тест**

```python
from app.domain.values import (
    BOARD_SIZE,
    MAX_MOVES,
    Color,
    GameStatus,
    color_of_move,
    color_to_move,
)


def test_board_constants():
    assert BOARD_SIZE == 15
    assert MAX_MOVES == 225


def test_color_of_move_alternates_from_black():
    assert color_of_move(0) is Color.BLACK
    assert color_of_move(1) is Color.WHITE
    assert color_of_move(224) is Color.BLACK


def test_color_to_move_by_move_count():
    assert color_to_move(0) is Color.BLACK   # пустая доска — ходят чёрные
    assert color_to_move(1) is Color.WHITE
    assert color_to_move(8) is Color.BLACK


def test_game_status_values_match_spec_enum():
    # значения попадут в БД и API (этапы 2–3) — фиксируем строки спека §4.3
    assert GameStatus.AWAITING_HUMAN.value == "awaiting_human"
    assert GameStatus.ENGINE_THINKING.value == "engine_thinking"
    assert GameStatus.FINISHED_BLACK.value == "finished_black"
    assert GameStatus.FINISHED_WHITE.value == "finished_white"
    assert GameStatus.FINISHED_DRAW.value == "finished_draw"
    assert GameStatus.FINISHED_BLACK.is_finished
    assert not GameStatus.AWAITING_HUMAN.is_finished
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_values.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain'`.

- [ ] **Step 3: Реализовать `backend/app/domain/values.py`**

```python
"""Базовые типы домена рэндзю. Без I/O."""

from enum import StrEnum

BOARD_SIZE = 15
MAX_MOVES = BOARD_SIZE * BOARD_SIZE

# Точка доски: (x, y), оба в 0..14. Ходы партии — список точек в порядке ходов;
# цвет хода определяется чётностью индекса (первый ход — чёрные).
Point = tuple[int, int]


class Color(StrEnum):
    BLACK = "black"
    WHITE = "white"


class GameStatus(StrEnum):
    AWAITING_HUMAN = "awaiting_human"
    ENGINE_THINKING = "engine_thinking"
    FINISHED_BLACK = "finished_black"
    FINISHED_WHITE = "finished_white"
    FINISHED_DRAW = "finished_draw"

    @property
    def is_finished(self) -> bool:
        return self in (
            GameStatus.FINISHED_BLACK,
            GameStatus.FINISHED_WHITE,
            GameStatus.FINISHED_DRAW,
        )


def color_of_move(index: int) -> Color:
    return Color.BLACK if index % 2 == 0 else Color.WHITE


def color_to_move(moves_count: int) -> Color:
    return color_of_move(moves_count)


class DomainError(Exception):
    """База для доменных ошибок."""


class MoveRejectReason(StrEnum):
    OUT_OF_BOARD = "out_of_board"
    OCCUPIED = "occupied"
    NOT_YOUR_TURN = "not_your_turn"
    FORBIDDEN = "forbidden"
    GAME_FINISHED = "game_finished"


class MoveRejected(DomainError):
    def __init__(self, reason: MoveRejectReason):
        self.reason = reason
        super().__init__(reason.value)


class UndoRejectReason(StrEnum):
    DISABLED = "disabled"
    ENGINE_THINKING = "engine_thinking"
    GAME_FINISHED = "game_finished"
    LIMIT_REACHED = "limit_reached"
    NOTHING_TO_UNDO = "nothing_to_undo"


class UndoRejected(DomainError):
    def __init__(self, reason: UndoRejectReason):
        self.reason = reason
        super().__init__(reason.value)
```

И `backend/app/domain/__init__.py` — пустой файл.

- [ ] **Step 4: Прогнать тест**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_values.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/domain backend/tests/unit/test_values.py
git -C /Users/alexey/code/Renju commit -m "feat(domain): board constants, colors, game status, domain errors"
```

---

### Task 4: Домен — исходы партии (`rules.py`)

Пятёрка чёрных — ровно 5 (оверлайн чёрных победой не является; до него и не дойдёт — фолы блокируются на вводе). Белые — 5 и больше (оверлайн белых = победа). Ничья — 225 камней без победы. Детекция — по последнему ходу (спек §10; это «демонская» часть, Rapfi исходов не сообщает).

**Files:**
- Create: `backend/app/domain/rules.py`
- Test: `backend/tests/unit/test_rules.py`

- [ ] **Step 1: Написать падающие тесты**

```python
from app.domain.rules import outcome_after
from app.domain.values import BOARD_SIZE, MAX_MOVES, GameStatus, Point


def interleave(blacks: list[Point], whites: list[Point]) -> list[Point]:
    """Сплести списки в порядок ходов: B, W, B, W, …"""
    moves: list[Point] = []
    for i in range(len(blacks) + len(whites)):
        moves.append(blacks[i // 2] if i % 2 == 0 else whites[i // 2])
    return moves


def test_empty_and_short_games_are_not_finished():
    assert outcome_after([]) is None
    assert outcome_after([(7, 7)]) is None


def test_black_five_horizontal_wins():
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]
    whites = [(0, 0), (2, 0), (4, 0), (6, 0)]  # вразброс — без побочных линий
    moves = interleave(blacks, whites)  # последний ход — чёрный (7,7)
    assert outcome_after(moves) is GameStatus.FINISHED_BLACK


def test_black_five_diagonal_wins():
    blacks = [(3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]
    whites = [(0, 5), (0, 7), (0, 9), (0, 11)]
    assert outcome_after(interleave(blacks, whites)) is GameStatus.FINISHED_BLACK


def test_black_four_is_not_a_win():
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7)]
    whites = [(0, 0), (2, 0), (4, 0)]
    assert outcome_after(interleave(blacks, whites)) is None


def test_black_overline_is_not_a_win():
    # 6 чёрных в ряд (на практике заблокировано фолами, но правило фиксируем)
    blacks = [(2, 7), (3, 7), (4, 7), (6, 7), (7, 7), (5, 7)]  # (5,7) замыкает шестёрку
    whites = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)]  # вразброс
    assert outcome_after(interleave(blacks, whites)) is None


def test_white_five_vertical_wins():
    blacks = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)]  # вразброс
    whites = [(7, 3), (7, 4), (7, 5), (7, 6), (7, 7)]
    moves = interleave(blacks, whites)  # последний ход — белый (7,7)
    assert outcome_after(moves) is GameStatus.FINISHED_WHITE


def test_white_overline_wins():
    blacks = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0)]  # вразброс
    whites = [(7, 2), (7, 3), (7, 4), (7, 6), (7, 7), (7, 5)]  # (7,5) замыкает шестёрку
    assert outcome_after(interleave(blacks, whites)) is GameStatus.FINISHED_WHITE


def test_win_detection_uses_only_last_move_color():
    # пятёрка белых уже стоит, но последний ход чёрный и ничего не выигрывает:
    # функция смотрит только на линию последнего хода (own пересобирается каждый раз)
    blacks = [(0, 0), (1, 1), (2, 2), (3, 3), (0, 4), (0, 6)]
    whites = [(7, 3), (7, 4), (7, 5), (7, 6), (7, 7)]
    moves = interleave(blacks, whites)  # 11 ходов, последний — чёрный (0,6)
    assert outcome_after(moves) is None


def test_full_board_without_five_is_draw():
    # Раскраска цвет(x,y) = (x + 2y) % 4 < 2: максимум 2 подряд в любом из
    # 4 направлений (горизонталь BBWW…, вертикаль BWBW…, диагонали BWWB…).
    # NB: раскраска 2×2-блоками (x//2+y//2)%2 НЕ подходит — на главной
    # диагонали (k,k) она даёт один цвет на все 15 клеток.
    blacks = [(x, y) for y in range(BOARD_SIZE) for x in range(BOARD_SIZE)
              if (x + 2 * y) % 4 < 2]
    whites = [(x, y) for y in range(BOARD_SIZE) for x in range(BOARD_SIZE)
              if (x + 2 * y) % 4 >= 2]
    assert len(blacks) == 113 and len(whites) == 112  # чёрные ходят первыми
    moves = interleave(blacks, whites)
    assert len(moves) == MAX_MOVES
    assert outcome_after(moves) is GameStatus.FINISHED_DRAW
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.rules'`.

- [ ] **Step 3: Реализовать `backend/app/domain/rules.py`**

```python
"""Исходы партии. Детекция по последнему ходу; чистые функции."""

from collections.abc import Sequence

from app.domain.values import MAX_MOVES, Color, GameStatus, Point, color_of_move

_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


def outcome_after(moves: Sequence[Point]) -> GameStatus | None:
    """Статус-исход после последнего хода или None, если партия продолжается.

    Рэндзю: чёрные выигрывают ровно пятёркой (оверлайн — не победа),
    белые — пятёркой и длиннее. Ничья — полная доска (225) без победы.

    Проверяется только линия последнего хода; набор своих камней (own)
    пересобирается за O(n) на каждый вызов — инкрементного состояния нет.
    """
    if not moves:
        return None
    last = moves[-1]
    mover = color_of_move(len(moves) - 1)
    own = {moves[i] for i in range(len(moves)) if color_of_move(i) is mover}
    for dx, dy in _DIRECTIONS:
        run = 1 + _ray(own, last, dx, dy) + _ray(own, last, -dx, -dy)
        if mover is Color.BLACK and run == 5:
            return GameStatus.FINISHED_BLACK
        if mover is Color.WHITE and run >= 5:
            return GameStatus.FINISHED_WHITE
    if len(moves) == MAX_MOVES:
        return GameStatus.FINISHED_DRAW
    return None


def _ray(own: set[Point], start: Point, dx: int, dy: int) -> int:
    """Сколько своих камней подряд от start в направлении (dx, dy), не считая start."""
    count = 0
    x, y = start[0] + dx, start[1] + dy
    while (x, y) in own:
        count += 1
        x, y = x + dx, y + dy
    return count
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_rules.py -v`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/domain/rules.py backend/tests/unit/test_rules.py
git -C /Users/alexey/code/Renju commit -m "feat(domain): game outcome detection (five / white overline / draw)"
```

---

### Task 5: Домен — валидация хода человека (`game.py`, часть 1)

Серверная подстраховка (спек §4.8, §10): фронт блокирует ввод сам, но сервер обязан отвергнуть ход не в свой черёд / в занятую клетку / в запрещённую точку / в законченной партии.

**Files:**
- Create: `backend/app/domain/game.py`
- Test: `backend/tests/unit/test_game.py`

- [ ] **Step 1: Написать падающие тесты**

```python
import pytest

from app.domain.game import validate_human_move
from app.domain.values import Color, GameStatus, MoveRejected, MoveRejectReason


def test_valid_first_black_move_passes():
    validate_human_move(
        moves=[], human_color=Color.BLACK, status=GameStatus.AWAITING_HUMAN,
        point=(7, 7), forbidden=[],
    )  # не бросает


def test_out_of_board_rejected():
    for bad in [(-1, 0), (0, -1), (15, 0), (0, 15)]:
        with pytest.raises(MoveRejected) as e:
            validate_human_move(
                moves=[], human_color=Color.BLACK, status=GameStatus.AWAITING_HUMAN,
                point=bad, forbidden=[],
            )
        assert e.value.reason is MoveRejectReason.OUT_OF_BOARD


def test_occupied_cell_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7), (8, 8)], human_color=Color.BLACK,
            status=GameStatus.AWAITING_HUMAN, point=(8, 8), forbidden=[],
        )
    assert e.value.reason is MoveRejectReason.OCCUPIED


def test_not_your_turn_rejected_by_color():
    # один камень на доске — очередь белых; человек играет чёрными
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7)], human_color=Color.BLACK,
            status=GameStatus.AWAITING_HUMAN, point=(8, 8), forbidden=[],
        )
    assert e.value.reason is MoveRejectReason.NOT_YOUR_TURN


def test_engine_thinking_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7), (8, 8)], human_color=Color.BLACK,
            status=GameStatus.ENGINE_THINKING, point=(9, 9), forbidden=[],
        )
    assert e.value.reason is MoveRejectReason.NOT_YOUR_TURN


def test_finished_game_rejected():
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7), (8, 8)], human_color=Color.BLACK,
            status=GameStatus.FINISHED_WHITE, point=(9, 9), forbidden=[],
        )
    assert e.value.reason is MoveRejectReason.GAME_FINISHED


def test_forbidden_point_rejected_for_black():
    with pytest.raises(MoveRejected) as e:
        validate_human_move(
            moves=[(7, 7), (8, 8)], human_color=Color.BLACK,
            status=GameStatus.AWAITING_HUMAN, point=(9, 9), forbidden=[(9, 9)],
        )
    assert e.value.reason is MoveRejectReason.FORBIDDEN
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_game.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.game'`.

- [ ] **Step 3: Реализовать `backend/app/domain/game.py`**

```python
"""Игровая логика партии: валидация хода человека, усечение undo. Чистые функции."""

from collections.abc import Sequence

from app.domain.values import (
    BOARD_SIZE,
    Color,
    GameStatus,
    MoveRejected,
    MoveRejectReason,
    Point,
    color_to_move,
)


def validate_human_move(
    *,
    moves: Sequence[Point],
    human_color: Color,
    status: GameStatus,
    point: Point,
    forbidden: Sequence[Point],
) -> None:
    """Бросает MoveRejected, если ход человека недопустим. Порядок проверок важен:
    сначала состояние партии, потом геометрия, потом фолы."""
    if status.is_finished:
        raise MoveRejected(MoveRejectReason.GAME_FINISHED)
    if status is not GameStatus.AWAITING_HUMAN:
        raise MoveRejected(MoveRejectReason.NOT_YOUR_TURN)
    if color_to_move(len(moves)) is not human_color:
        raise MoveRejected(MoveRejectReason.NOT_YOUR_TURN)
    x, y = point
    if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
        raise MoveRejected(MoveRejectReason.OUT_OF_BOARD)
    if point in set(moves):
        raise MoveRejected(MoveRejectReason.OCCUPIED)
    if human_color is Color.BLACK and point in set(forbidden):
        raise MoveRejected(MoveRejectReason.FORBIDDEN)
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_game.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/domain/game.py backend/tests/unit/test_game.py
git -C /Users/alexey/code/Renju commit -m "feat(domain): human move validation"
```

---

### Task 6: Домен — усечение undo (`game.py`, часть 2)

Механика спека §4.8: откат до предыдущего состояния «твой ход». Обычно убирает ход ИИ + твой; если партия кончилась твоим ходом — только твой.

**Files:**
- Modify: `backend/app/domain/game.py` (добавить функцию)
- Test: `backend/tests/unit/test_game.py` (добавить тесты)

- [ ] **Step 1: Дописать падающие тесты в `test_game.py`**

```python
from app.domain.game import undo_truncate
from app.domain.values import UndoRejected, UndoRejectReason


def test_undo_black_human_removes_engine_and_own_move():
    # чёрный человек: [B(7,7), W(8,8)] → снова ход чёрных, убрать оба
    assert undo_truncate(moves=[(7, 7), (8, 8)], human_color=Color.BLACK) == []


def test_undo_black_human_after_own_finishing_move_removes_one():
    # партия закончилась ходом чёрного человека (нечётная длина) → убрать один
    moves = [(7, 7), (8, 8), (7, 8)]
    assert undo_truncate(moves=moves, human_color=Color.BLACK) == [(7, 7), (8, 8)]


def test_undo_white_human_removes_engine_and_own_move():
    # белый человек: [B, W, B] → очередь белых после усечения до 1 камня
    moves = [(7, 7), (8, 8), (9, 9)]
    assert undo_truncate(moves=moves, human_color=Color.WHITE) == [(7, 7)]


def test_undo_white_human_after_own_finishing_move_removes_one():
    moves = [(7, 7), (8, 8), (9, 9), (8, 9)]
    assert undo_truncate(moves=moves, human_color=Color.WHITE) == [(7, 7), (8, 8), (9, 9)]


def test_undo_black_human_with_empty_board_rejected():
    with pytest.raises(UndoRejected) as e:
        undo_truncate(moves=[], human_color=Color.BLACK)
    assert e.value.reason is UndoRejectReason.NOTHING_TO_UNDO


def test_undo_white_human_with_only_engine_move_rejected():
    # у белого человека ещё нет своих ходов — откатывать нечего
    with pytest.raises(UndoRejected) as e:
        undo_truncate(moves=[(7, 7)], human_color=Color.WHITE)
    assert e.value.reason is UndoRejectReason.NOTHING_TO_UNDO
```

- [ ] **Step 2: Убедиться, что новые тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_game.py -v`
Expected: FAIL — `ImportError: cannot import name 'undo_truncate'`.

- [ ] **Step 3: Дописать в `backend/app/domain/game.py`**

Расширить импорт из `app.domain.values` вверху файла — добавить `UndoRejected, UndoRejectReason`:

```python
from app.domain.values import (
    BOARD_SIZE,
    Color,
    GameStatus,
    MoveRejected,
    MoveRejectReason,
    Point,
    UndoRejected,
    UndoRejectReason,
    color_to_move,
)
```

И добавить функцию:

```python
def undo_truncate(*, moves: Sequence[Point], human_color: Color) -> list[Point]:
    """Усечь ходы до предыдущего состояния «ход человека».

    Новая длина k — наибольшая k < len(moves), при которой очередь человека:
    k чётно для чёрных, нечётно для белых. Обычно убирает 2 камня (ход ИИ + свой),
    после завершающего хода человека — 1.
    """
    target_parity = 0 if human_color is Color.BLACK else 1
    k = len(moves) - 1
    while k >= 0 and k % 2 != target_parity:
        k -= 1
    if k < 0:
        raise UndoRejected(UndoRejectReason.NOTHING_TO_UNDO)
    return list(moves[:k])
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_game.py -v`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/domain/game.py backend/tests/unit/test_game.py
git -C /Users/alexey/code/Renju commit -m "feat(domain): undo truncation to previous human-turn state"
```

---

### Task 7: Домен — undo-политика (`undo.py`)

Глобальная per-user настройка (спек §4.3, §4.8): `enabled` / `limit` (число | безлимит) / `after_game_end`. Undo разрешён, когда сервер не считает.

**Files:**
- Create: `backend/app/domain/undo.py`
- Test: `backend/tests/unit/test_undo.py`

- [ ] **Step 1: Написать падающие тесты**

```python
import pytest

from app.domain.undo import UndoPolicy, check_undo
from app.domain.values import GameStatus, UndoRejected, UndoRejectReason


def policy(**kw) -> UndoPolicy:
    return UndoPolicy(**{"enabled": True, "limit": None, "after_game_end": True, **kw})


def test_default_policy_allows_undo_in_awaiting_human():
    check_undo(policy=policy(), status=GameStatus.AWAITING_HUMAN, undo_count=0)


def test_disabled_policy_rejects():
    with pytest.raises(UndoRejected) as e:
        check_undo(policy=policy(enabled=False), status=GameStatus.AWAITING_HUMAN, undo_count=0)
    assert e.value.reason is UndoRejectReason.DISABLED


def test_engine_thinking_rejects():
    with pytest.raises(UndoRejected) as e:
        check_undo(policy=policy(), status=GameStatus.ENGINE_THINKING, undo_count=0)
    assert e.value.reason is UndoRejectReason.ENGINE_THINKING


def test_after_game_end_allowed_when_enabled():
    check_undo(policy=policy(), status=GameStatus.FINISHED_BLACK, undo_count=0)


def test_after_game_end_rejected_when_disabled():
    with pytest.raises(UndoRejected) as e:
        check_undo(
            policy=policy(after_game_end=False), status=GameStatus.FINISHED_DRAW, undo_count=0
        )
    assert e.value.reason is UndoRejectReason.GAME_FINISHED


def test_limit_reached_rejects():
    with pytest.raises(UndoRejected) as e:
        check_undo(policy=policy(limit=3), status=GameStatus.AWAITING_HUMAN, undo_count=3)
    assert e.value.reason is UndoRejectReason.LIMIT_REACHED


def test_under_limit_allows():
    check_undo(policy=policy(limit=3), status=GameStatus.AWAITING_HUMAN, undo_count=2)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_undo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.undo'`.

- [ ] **Step 3: Реализовать `backend/app/domain/undo.py`**

```python
"""Undo-политика пользователя (глобальная настройка, спек §4.3/§4.8)."""

from dataclasses import dataclass

from app.domain.values import GameStatus, UndoRejected, UndoRejectReason


@dataclass(frozen=True)
class UndoPolicy:
    enabled: bool = True
    limit: int | None = None  # None — без лимита
    after_game_end: bool = True


def check_undo(*, policy: UndoPolicy, status: GameStatus, undo_count: int) -> None:
    """Бросает UndoRejected, если откат запрещён политикой или состоянием партии."""
    if not policy.enabled:
        raise UndoRejected(UndoRejectReason.DISABLED)
    if status is GameStatus.ENGINE_THINKING:
        raise UndoRejected(UndoRejectReason.ENGINE_THINKING)
    if status.is_finished and not policy.after_game_end:
        raise UndoRejected(UndoRejectReason.GAME_FINISHED)
    if policy.limit is not None and undo_count >= policy.limit:
        raise UndoRejected(UndoRejectReason.LIMIT_REACHED)
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_undo.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/domain/undo.py backend/tests/unit/test_undo.py
git -C /Users/alexey/code/Renju commit -m "feat(domain): undo policy checks"
```

---

### Task 8: Домен — уровни сложности (`levels.py`)

Спек §4.5: enum-уровни, массив живёт на бэке, транслируется в `INFO STRENGTH` + `INFO TIMEOUT_TURN`. Числа предварительные — калибруются позже, инвариант: strength монотонно растёт, master = 100.

**Files:**
- Create: `backend/app/domain/levels.py`
- Test: `backend/tests/unit/test_levels.py`

- [ ] **Step 1: Написать падающие тесты**

```python
import pytest

from app.domain.levels import LEVELS, Level


def test_all_levels_have_params():
    assert set(LEVELS) == set(Level)


def test_strength_in_engine_range_and_monotonic():
    ordered = [Level.NOVICE, Level.EASY, Level.MEDIUM, Level.HARD, Level.MASTER]
    strengths = [LEVELS[lv].strength for lv in ordered]
    assert all(0 <= s <= 100 for s in strengths)
    assert strengths == sorted(strengths)
    assert strengths[-1] == 100  # master — без ослабления


def test_timeouts_positive():
    assert all(p.timeout_turn_ms > 0 for p in LEVELS.values())


def test_params_immutable():
    with pytest.raises(AttributeError):  # frozen dataclass → FrozenInstanceError (подкласс)
        LEVELS[Level.NOVICE].strength = 99  # type: ignore[misc]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_levels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.levels'`.

- [ ] **Step 3: Реализовать `backend/app/domain/levels.py`**

```python
"""Уровни сложности: enum → параметры Rapfi (спек §4.5).

Числа предварительные, калибруются на живой игре. Клиент значений не знает —
получает только id+имя (этап 3, GET /levels).
"""

from dataclasses import dataclass
from enum import StrEnum


class Level(StrEnum):
    NOVICE = "novice"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    MASTER = "master"


@dataclass(frozen=True)
class EngineParams:
    strength: int  # INFO strength, 0..100 (100 — без человеческого ослабления)
    timeout_turn_ms: int  # INFO timeout_turn


LEVELS: dict[Level, EngineParams] = {
    Level.NOVICE: EngineParams(strength=10, timeout_turn_ms=1000),
    Level.EASY: EngineParams(strength=30, timeout_turn_ms=1500),
    Level.MEDIUM: EngineParams(strength=55, timeout_turn_ms=2500),
    Level.HARD: EngineParams(strength=80, timeout_turn_ms=4000),
    Level.MASTER: EngineParams(strength=100, timeout_turn_ms=7000),
}
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_levels.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/domain/levels.py backend/tests/unit/test_levels.py
git -C /Users/alexey/code/Renju commit -m "feat(domain): difficulty levels mapped to engine params"
```

---

### Task 9: Адаптер — парсинг протокола (`protocol.py`, часть 1)

Чистые функции без I/O. Ожидаемые строки — из живых прогонов (см. «Контекст» выше).

**Files:**
- Create: `backend/app/rapfi/__init__.py` (пустой)
- Create: `backend/app/rapfi/protocol.py`
- Test: `backend/tests/unit/test_protocol.py`

- [ ] **Step 1: Написать падающие тесты**

```python
import pytest

from app.rapfi.protocol import LineKind, ProtocolError, parse_line


def test_parse_ok():
    assert parse_line("OK").kind is LineKind.OK


def test_parse_move():
    parsed = parse_line("5,4")
    assert parsed.kind is LineKind.MOVE
    assert parsed.move == (5, 4)


def test_parse_move_two_digit_coords():
    assert parse_line("14,10").move == (14, 10)


def test_move_out_of_board_is_protocol_error():
    with pytest.raises(ProtocolError):
        parse_line("15,0")


def test_parse_noise_lines():
    for raw in [
        "MESSAGE Speed 408K | Depth 7-9 | Eval -66 | Node 817 | Time 2ms",
        "MESSAGE mix9svq nnue: load weight from engine/rapfi/Networks/...",
        "DEBUG something",
        "INFO whatever",
        'name="Rapfi", version="0.43.02", author="Rapfi developers", country="China"',
        "",
    ]:
        assert parse_line(raw).kind is LineKind.NOISE, raw


def test_parse_error_line():
    parsed = parse_line("ERROR Unknown command: FOOBAR")
    assert parsed.kind is LineKind.ERROR
    assert "FOOBAR" in parsed.text


def test_parse_forbid_single():
    parsed = parse_line("FORBID 0707.")
    assert parsed.kind is LineKind.FORBID
    assert parsed.forbidden == ((7, 7),)


def test_parse_forbid_multiple_and_two_digit():
    parsed = parse_line("FORBID 07071412.")
    assert parsed.forbidden == ((7, 7), (14, 12))


def test_parse_forbid_empty():
    parsed = parse_line("FORBID .")
    assert parsed.kind is LineKind.FORBID
    assert parsed.forbidden == ()


def test_parse_forbid_malformed_is_protocol_error():
    with pytest.raises(ProtocolError):
        parse_line("FORBID 077.")  # нечётное число цифр — битая склейка
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.rapfi'`.

- [ ] **Step 3: Реализовать парсинг в `backend/app/rapfi/protocol.py`**

```python
"""Протокол Piskvork/yx Rapfi: сборка команд и парсинг строк. Чистые функции.

Форматы сняты с реального бинаря (Rapfi 0.43.02):
- ход: голая строка "x,y" (например "5,4");
- фолы: "FORBID 0707." — пары %02d%02d (x, потом y), завершаются точкой; пусто: "FORBID .";
- ошибки: "ERROR <текст>"; подтверждение START: "OK";
- шум: "MESSAGE …", "DEBUG …", "INFO …" и прочее не подходящее под форматы выше.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.values import BOARD_SIZE, Point

_MOVE_RE = re.compile(r"^(\d{1,2}),(\d{1,2})$")
_FORBID_RE = re.compile(r"^FORBID ?((?:\d{4})*)\.$")


class ProtocolError(Exception):
    """Ответ движка не соответствует протоколу."""


class LineKind(StrEnum):
    OK = "ok"
    MOVE = "move"
    FORBID = "forbid"
    ERROR = "error"
    NOISE = "noise"


@dataclass(frozen=True)
class ParsedLine:
    kind: LineKind
    text: str
    move: Point | None = None
    forbidden: tuple[Point, ...] | None = None


def parse_line(raw: str) -> ParsedLine:
    line = raw.strip()
    if line == "OK":
        return ParsedLine(LineKind.OK, line)
    if line.startswith("ERROR"):
        return ParsedLine(LineKind.ERROR, line)
    if m := _MOVE_RE.match(line):
        move = (int(m.group(1)), int(m.group(2)))
        if not _on_board(move):
            raise ProtocolError(f"move out of board: {line!r}")
        return ParsedLine(LineKind.MOVE, line, move=move)
    if line.startswith("FORBID"):
        m = _FORBID_RE.match(line)
        if not m:
            raise ProtocolError(f"malformed FORBID line: {line!r}")
        digits = m.group(1)
        points = tuple(
            (int(digits[i : i + 2]), int(digits[i + 2 : i + 4]))
            for i in range(0, len(digits), 4)
        )
        if not all(_on_board(p) for p in points):
            raise ProtocolError(f"forbid point out of board: {line!r}")
        return ParsedLine(LineKind.FORBID, line, forbidden=points)
    return ParsedLine(LineKind.NOISE, line)


def _on_board(point: Point) -> bool:
    return 0 <= point[0] < BOARD_SIZE and 0 <= point[1] < BOARD_SIZE
```

И `backend/app/rapfi/__init__.py` — пустой файл.

(Примечание: `FORBID 077.` имеет 3 цифры — под `(?:\d{4})*` не подходит, регулярка отвергает → `ProtocolError`. `_FORBID_RE` допускает опциональный пробел перед группой: реальные выводы — `FORBID 0707.` и `FORBID .`, оба покрыты.)

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_protocol.py -v`
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/rapfi backend/tests/unit/test_protocol.py
git -C /Users/alexey/code/Renju commit -m "feat(rapfi): protocol line parsing (move/forbid/error/noise)"
```

---

### Task 10: Адаптер — сборка команд (`protocol.py`, часть 2) + анти-инъекция

Спек §5.2: сырой ввод в stdin движка не попадает никогда. Команды строятся только из провалидированных `int` 0..14; всё прочее отвергается до движка.

**Files:**
- Modify: `backend/app/rapfi/protocol.py`
- Test: `backend/tests/unit/test_protocol.py` (добавить тесты)

- [ ] **Step 1: Дописать падающие тесты в `test_protocol.py`**

```python
from app.domain.levels import EngineParams
from app.rapfi.protocol import (
    forbid_commands,
    init_commands,
    position_commands,
)


def test_init_commands():
    params = EngineParams(strength=55, timeout_turn_ms=2500)
    assert init_commands(params) == [
        "START 15",
        "INFO rule 4",
        "INFO strength 55",
        "INFO timeout_turn 2500",
    ]


def test_position_commands_empty_board_is_begin():
    assert position_commands([]) == ["BEGIN"]


def test_position_commands_engine_moves_second():
    # человек-чёрный сходил (7,7); очередь движка (белые): его камней нет, who=2 у чужого
    # точная строка проверена живым прогоном: BOARD / 7,7,2 / DONE → движок отвечает ходом
    assert position_commands([(7, 7)]) == ["BOARD", "7,7,2", "DONE"]


def test_position_commands_engine_is_black():
    # движок-чёрный сходил (7,7), человек-белый ответил (8,8); очередь движка:
    # его камень — who=1, человеческий — who=2 (проверено живым прогоном)
    assert position_commands([(7, 7), (8, 8)]) == ["BOARD", "7,7,1", "8,8,2", "DONE"]


def test_forbid_commands():
    assert forbid_commands([(8, 7), (0, 0)]) == [
        "YXBOARD",
        "8,7,1",
        "0,0,2",
        "DONE",
        "YXSHOWFORBID",
    ]


def test_position_commands_rejects_non_int_coordinates():
    import pytest
    from app.rapfi.protocol import ProtocolError

    for bad in [(7.0, 7), ("7", 7), (7, None), (True, 3)]:
        with pytest.raises(ProtocolError):
            position_commands([bad])  # type: ignore[list-item]


def test_position_commands_rejects_out_of_board_and_duplicates():
    import pytest
    from app.rapfi.protocol import ProtocolError

    with pytest.raises(ProtocolError):
        position_commands([(15, 0)])
    with pytest.raises(ProtocolError):
        position_commands([(-1, 3)])
    with pytest.raises(ProtocolError):
        position_commands([(7, 7), (7, 7)])
```

- [ ] **Step 2: Убедиться, что новые тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_protocol.py -v`
Expected: FAIL — `ImportError: cannot import name 'init_commands'`.

- [ ] **Step 3: Дописать в `backend/app/rapfi/protocol.py`**

Два новых импорта — **в начало файла**, к остальным (иначе ruff E402):

```python
from collections.abc import Sequence

from app.domain.levels import EngineParams
```

Функции — в конец файла:

```python
def init_commands(params: EngineParams) -> list[str]:
    """Переинициализация перед каждым расчётом — состояние партий не протекает."""
    return [
        f"START {BOARD_SIZE}",
        "INFO rule 4",
        f"INFO strength {params.strength}",
        f"INFO timeout_turn {params.timeout_turn_ms}",
    ]


def position_commands(moves: Sequence[Point]) -> list[str]:
    """BOARD-блок для запроса хода (пустая позиция — BEGIN).

    who относительно стороны-на-ходу: 1 — её камни, 2 — соперника.
    Камни в порядке ходов (первый — чёрный)."""
    _validate_moves(moves)
    if not moves:
        return ["BEGIN"]
    return ["BOARD", *_stone_lines(moves), "DONE"]


def forbid_commands(moves: Sequence[Point]) -> list[str]:
    """YXBOARD-блок (ставит доску без расчёта) + запрос запрещённых точек."""
    _validate_moves(moves)
    return ["YXBOARD", *_stone_lines(moves), "DONE", "YXSHOWFORBID"]


def _stone_lines(moves: Sequence[Point]) -> list[str]:
    side_to_move_parity = len(moves) % 2
    return [
        f"{x},{y},{1 if i % 2 == side_to_move_parity else 2}"
        for i, (x, y) in enumerate(moves)
    ]


def _validate_moves(moves: Sequence[Point]) -> None:
    """Анти-инъекция (спек §5.2): в stdin движка уходят только int 0..14.

    bool — подкласс int, отвергаем явно. Дубликаты — битая позиция."""
    seen: set[Point] = set()
    for point in moves:
        if not (isinstance(point, tuple) and len(point) == 2):
            raise ProtocolError(f"malformed point: {point!r}")
        x, y = point
        if isinstance(x, bool) or isinstance(y, bool):
            raise ProtocolError(f"non-int coordinates: {point!r}")
        if not (isinstance(x, int) and isinstance(y, int)):
            raise ProtocolError(f"non-int coordinates: {point!r}")
        if not _on_board((x, y)):
            raise ProtocolError(f"point out of board: {point!r}")
        if (x, y) in seen:
            raise ProtocolError(f"duplicate point: {point!r}")
        seen.add((x, y))
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_protocol.py -v`
Expected: `18 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/rapfi/protocol.py backend/tests/unit/test_protocol.py
git -C /Users/alexey/code/Renju commit -m "feat(rapfi): command building with strict anti-injection validation"
```

---

### Task 11: Настройки приложения (`config.py`)

**Files:**
- Create: `backend/app/config.py`
- Test: `backend/tests/unit/test_config.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Написать падающие тесты**

`backend/tests/unit/test_config.py`:

```python
from pathlib import Path

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
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`.

- [ ] **Step 3: Реализовать `backend/app/config.py`**

```python
"""Настройки приложения (pydantic-settings, env-префикс RENJU_)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RENJU_", env_file=".env", extra="ignore")

    rapfi_bin: Path | None = None  # RENJU_RAPFI_BIN
    rapfi_config: Path = REPO_ROOT / "engine" / "config.toml"  # RENJU_RAPFI_CONFIG
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
                "pbrain-rapfi не найден: собери движок (engine/build.sh) "
                "или укажи RENJU_RAPFI_BIN"
            )
        return candidates[0]
```

(Голая ссылка на `REPO_ROOT` внутри метода резолвится через глобали модуля при каждом вызове — поэтому `monkeypatch.setattr("app.config.REPO_ROOT", …)` в тестах работает без хитростей. Дефолт `rapfi_config` вычисляется один раз при определении класса — тест `test_default_rapfi_config_path` использует непропатченный `REPO_ROOT`.)

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_config.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/config.py backend/tests/unit/test_config.py
git -C /Users/alexey/code/Renju commit -m "feat(config): settings with rapfi binary discovery"
```

---

### Task 12: Адаптер — процесс (`process.py`)

Тонкая обёртка над `asyncio.subprocess`: spawn, запись строк, чтение строки, terminate-с-эскалацией. Интеграционный тест — против реального бинаря.

**Files:**
- Create: `backend/app/rapfi/process.py`
- Test: `backend/tests/integration/test_process.py` (каталог `tests/integration/` создаётся этим файлом; `__init__.py` тестовым каталогам не нужен)
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Заполнить `backend/tests/conftest.py`**

```python
import pytest

from app.config import Settings


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
    from app.config import REPO_ROOT

    return bin_path, settings.rapfi_config, REPO_ROOT
```

- [ ] **Step 2: Написать падающий интеграционный тест**

`backend/tests/integration/test_process.py`:

```python
import pytest

from app.rapfi.process import EngineProcessDied, RapfiProcess


async def test_spawn_about_and_terminate(rapfi_paths):
    bin_path, config_path, cwd = rapfi_paths
    proc = await RapfiProcess.spawn(bin_path=bin_path, config_path=config_path, cwd=cwd)
    try:
        assert proc.alive
        await proc.send(["ABOUT"])
        line = await proc.read_line()
        while 'name="Rapfi"' not in line:  # пропустить MESSAGE о загрузке конфига
            line = await proc.read_line()
        assert 'name="Rapfi"' in line
    finally:
        await proc.terminate(grace_s=2.0)
    assert not proc.alive


async def test_read_after_death_raises(rapfi_paths):
    bin_path, config_path, cwd = rapfi_paths
    proc = await RapfiProcess.spawn(bin_path=bin_path, config_path=config_path, cwd=cwd)
    await proc.send(["END"])  # штатное завершение по протоколу
    with pytest.raises(EngineProcessDied):
        # дочитываем возможный хвост; после EOF обязан брошен EngineProcessDied
        for _ in range(100):
            await proc.read_line()
    await proc.terminate(grace_s=2.0)
    assert not proc.alive
```

- [ ] **Step 3: Убедиться, что тест падает**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/integration/test_process.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.rapfi.process'`.

- [ ] **Step 4: Реализовать `backend/app/rapfi/process.py`**

```python
"""OS-процесс Rapfi: spawn, обмен строками, завершение. Никакой логики протокола."""

import asyncio
from asyncio.subprocess import DEVNULL, PIPE
from pathlib import Path


class EngineProcessDied(Exception):
    """Процесс движка завершился/закрыл stdout."""


class RapfiProcess:
    def __init__(self, proc: asyncio.subprocess.Process):
        self._proc = proc

    @classmethod
    async def spawn(cls, *, bin_path: Path, config_path: Path, cwd: Path) -> "RapfiProcess":
        proc = await asyncio.create_subprocess_exec(
            str(bin_path),
            "--config",
            str(config_path),
            cwd=str(cwd),
            stdin=PIPE,
            stdout=PIPE,
            stderr=DEVNULL,
        )
        return cls(proc)

    @property
    def alive(self) -> bool:
        return self._proc.returncode is None

    async def send(self, lines: list[str]) -> None:
        if not lines:
            return
        if not self.alive:
            raise EngineProcessDied("send to dead engine process")
        if self._proc.stdin is None:
            raise EngineProcessDied("engine stdin is not a pipe")
        self._proc.stdin.write(("\n".join(lines) + "\n").encode())
        try:
            await self._proc.stdin.drain()
        except (ConnectionResetError, BrokenPipeError) as e:
            raise EngineProcessDied(str(e)) from e

    async def read_line(self) -> str:
        if self._proc.stdout is None:
            raise EngineProcessDied("engine stdout is not a pipe")
        raw = await self._proc.stdout.readline()
        if not raw:
            raise EngineProcessDied("engine stdout closed (EOF)")
        return raw.decode(errors="replace").strip()

    async def terminate(self, *, grace_s: float) -> None:
        """terminate → ждём grace_s → kill. Идемпотентно."""
        if not self.alive:
            return
        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=grace_s)
        except TimeoutError:
            self._proc.kill()
            await self._proc.wait()
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/integration/test_process.py -v`
Expected: `2 passed` (живой движок: суммарно ~2–5 с).

- [ ] **Step 6: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/rapfi/process.py backend/tests/integration/test_process.py backend/tests/conftest.py
git -C /Users/alexey/code/Renju commit -m "feat(rapfi): engine subprocess lifecycle wrapper"
```

---

### Task 13: Адаптер — фасад `compute_move` / `forbidden_points` (`adapter.py`)

Сердце этапа. Один владелец процесса, `asyncio.Lock` (лимит одновременных расчётов = 1, спек §4.2), переинициализация на каждый запрос, wall-clock таймаут с запасом над `timeout_turn`, kill+respawn+однократный повтор при сбое.

**Files:**
- Create: `backend/app/rapfi/adapter.py`
- Test: `backend/tests/integration/test_adapter.py`
- Create: `backend/tests/integration/fixtures/hang_engine.sh`

- [ ] **Step 1: Написать падающие интеграционные тесты**

`backend/tests/integration/test_adapter.py`:

```python
import asyncio
from pathlib import Path

import pytest

from app.domain.levels import LEVELS, EngineParams, Level
from app.domain.values import BOARD_SIZE
from app.rapfi.adapter import EngineError, RapfiAdapter

FAST = EngineParams(strength=100, timeout_turn_ms=1000)


@pytest.fixture
async def adapter(rapfi_paths):
    bin_path, config_path, cwd = rapfi_paths
    a = RapfiAdapter(bin_path=bin_path, config_path=config_path, cwd=cwd)
    yield a
    await a.close()


def on_board(p):
    return 0 <= p[0] < BOARD_SIZE and 0 <= p[1] < BOARD_SIZE


async def test_compute_move_on_empty_board(adapter):
    move = await adapter.compute_move([], FAST)
    assert on_board(move)


async def test_compute_move_replies_to_human_move(adapter):
    move = await adapter.compute_move([(7, 7)], FAST)
    assert on_board(move)
    assert move != (7, 7)  # не в занятую клетку


async def test_state_isolation_between_requests(adapter):
    # партия A: 8 камней; затем партия B: 1 камень — ход для B не должен
    # учитывать камни A (т.е. может встать на клетку, занятую только в A)
    game_a = [(0, 0), (14, 14), (0, 1), (14, 13), (0, 2), (14, 12), (0, 3), (14, 11)]
    await adapter.compute_move(game_a, FAST)
    move_b = await adapter.compute_move([(7, 7)], FAST)
    assert on_board(move_b)
    assert move_b != (7, 7)


async def test_forbidden_points_on_double_three(adapter):
    # позиция проверена живым прогоном: двойная тройка чёрных в (7,7)
    moves = [(8, 7), (0, 0), (9, 7), (0, 2), (7, 8), (0, 4), (7, 9), (0, 6)]
    forbidden = await adapter.forbidden_points(moves)
    assert (7, 7) in forbidden


async def test_forbidden_points_empty_board(adapter):
    assert await adapter.forbidden_points([]) == []


async def test_forbidden_points_when_white_to_move_is_empty(adapter):
    # нечётное число камней — ход белых, у белых фолов нет; движок не дёргаем
    assert await adapter.forbidden_points([(7, 7)]) == []


async def test_recovers_after_engine_crash(adapter):
    await adapter.compute_move([], FAST)
    await adapter._proc.terminate(grace_s=0.1)  # имитация внешнего краха движка
    move = await adapter.compute_move([(7, 7)], FAST)  # respawn + повтор
    assert on_board(move)


async def test_hanging_engine_killed_by_wall_clock(rapfi_paths):
    _, config_path, cwd = rapfi_paths
    hang = Path(__file__).parent / "fixtures" / "hang_engine.sh"
    a = RapfiAdapter(bin_path=hang, config_path=config_path, cwd=cwd, wall_clock_slack_s=0.2)
    try:
        params = EngineParams(strength=100, timeout_turn_ms=200)
        with pytest.raises(EngineError):
            await a.compute_move([(7, 7)], params)
        assert a._proc is None or not a._proc.alive  # зависший процесс убит
    finally:
        await a.close()


async def test_concurrent_requests_serialized(adapter):
    moves = await asyncio.gather(
        adapter.compute_move([], FAST),
        adapter.compute_move([(7, 7)], FAST),
    )
    assert all(on_board(m) for m in moves)


async def test_real_levels_work_end_to_end(adapter):
    move = await adapter.compute_move([(7, 7)], LEVELS[Level.NOVICE])
    assert on_board(move)
```

`backend/tests/integration/fixtures/hang_engine.sh`:

```bash
#!/bin/sh
# Заглушка «зависший движок»: молчит вечно, на команды не отвечает.
exec sleep 600
```

Run: `chmod +x /Users/alexey/code/Renju/backend/tests/integration/fixtures/hang_engine.sh`

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/integration/test_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.rapfi.adapter'`.

- [ ] **Step 3: Реализовать `backend/app/rapfi/adapter.py`**

```python
"""Фасад движка: «дай ход» и «дай фолы». Владеет процессом Rapfi.

Гарантии:
- одновременно выполняется не больше одного расчёта (asyncio.Lock);
- перед каждым расчётом движок переинициализируется (START/INFO/позиция);
- зависший или умерший процесс убивается по wall-clock таймауту и
  пересоздаётся; запрос повторяется один раз, дальше — EngineError.
"""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from app.domain.levels import EngineParams
from app.domain.values import Point
from app.rapfi.process import EngineProcessDied, RapfiProcess
from app.rapfi.protocol import (
    LineKind,
    ParsedLine,
    ProtocolError,
    forbid_commands,
    init_commands,
    parse_line,
    position_commands,
)

# Сколько добавить к timeout_turn движка до wall-clock kill: движок укладывается
# в свой бюджет сам, запас покрывает инициализацию (загрузку весов) и парсинг.
_WALL_CLOCK_SLACK_S = 5.0
_FORBID_TIMEOUT_S = 10.0
_FORBID_PARAMS = EngineParams(strength=100, timeout_turn_ms=1000)


class EngineError(Exception):
    """Движок не смог посчитать (после повтора). Несёт текст причины."""


class RapfiAdapter:
    def __init__(
        self,
        *,
        bin_path: Path,
        config_path: Path,
        cwd: Path,
        kill_grace_s: float = 2.0,
        wall_clock_slack_s: float = _WALL_CLOCK_SLACK_S,
    ):
        self._bin_path = bin_path
        self._config_path = config_path
        self._cwd = cwd
        self._kill_grace_s = kill_grace_s
        self._wall_clock_slack_s = wall_clock_slack_s
        self._lock = asyncio.Lock()
        self._proc: RapfiProcess | None = None

    async def compute_move(self, moves: Sequence[Point], params: EngineParams) -> Point:
        """Ход движка для позиции. Позиция — полный список ходов партии."""
        commands = init_commands(params) + position_commands(moves)
        timeout = params.timeout_turn_ms / 1000 + self._wall_clock_slack_s
        async with self._lock:
            parsed = await self._request(commands, LineKind.MOVE, timeout)
        if parsed.move is None:
            raise EngineError("engine returned no move")
        if parsed.move in set(moves):
            raise EngineError(f"engine returned occupied cell: {parsed.move}")
        return parsed.move

    async def forbidden_points(self, moves: Sequence[Point]) -> list[Point]:
        """Запрещённые точки для чёрных. Непусто только когда ход чёрных."""
        if len(moves) % 2 != 0:
            return []
        commands = init_commands(_FORBID_PARAMS) + forbid_commands(moves)
        async with self._lock:
            parsed = await self._request(commands, LineKind.FORBID, _FORBID_TIMEOUT_S)
        if parsed.forbidden is None:
            raise EngineError("engine returned no forbidden list")
        return list(parsed.forbidden)

    async def close(self) -> None:
        async with self._lock:
            if self._proc is not None:
                await self._proc.terminate(grace_s=self._kill_grace_s)
                self._proc = None

    # --- внутреннее -----------------------------------------------------

    async def _request(self, commands: list[str], want: LineKind, timeout_s: float) -> ParsedLine:
        """Одна попытка + один повтор на свежем процессе. Вызывать под self._lock."""
        try:
            return await self._attempt(commands, want, timeout_s)
        except (TimeoutError, EngineProcessDied, ProtocolError):
            await self._kill_proc()
        try:
            return await self._attempt(commands, want, timeout_s)
        except (TimeoutError, EngineProcessDied, ProtocolError) as e:
            await self._kill_proc()
            raise EngineError(f"engine failed twice: {e!r}") from e

    async def _attempt(self, commands: list[str], want: LineKind, timeout_s: float) -> ParsedLine:
        # spawn намеренно вне asyncio.timeout: create_subprocess_exec не блокирует
        # (веса грузятся лениво на первой stdin-команде, уже под таймаутом ниже).
        # Не переносить блокирующую работу в _ensure_proc — сбежит от wall-clock.
        proc = await self._ensure_proc()
        async with asyncio.timeout(timeout_s):
            await proc.send(commands)
            while True:
                parsed = parse_line(await proc.read_line())
                if parsed.kind is want:
                    return parsed
                if parsed.kind is LineKind.ERROR:
                    raise ProtocolError(parsed.text)

    async def _ensure_proc(self) -> RapfiProcess:
        if self._proc is None or not self._proc.alive:
            self._proc = await RapfiProcess.spawn(
                bin_path=self._bin_path, config_path=self._config_path, cwd=self._cwd
            )
        return self._proc

    async def _kill_proc(self) -> None:
        if self._proc is not None:
            await self._proc.terminate(grace_s=self._kill_grace_s)
            self._proc = None
```

- [ ] **Step 4: Прогнать тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/integration/test_adapter.py -v`
Expected: `10 passed` (займёт ~10–30 с: живые расчёты).

Примечания к ожидаемому поведению:
- `test_hanging_engine_killed_by_wall_clock`: wall-clock = `0.2 с (timeout_turn) + 0.2 с (slack через DI) = 0.4 с` на попытку; две попытки + terminate-grace — суммарно ~1 с, затем `EngineError`. (Slack вынесен в параметр конструктора `wall_clock_slack_s`; в проде дефолт 5 с покрывает загрузку весов, в тесте — 0.2 с для скорости.)
- `test_recovers_after_engine_crash`: первый `_attempt` упадёт `EngineProcessDied` при send/read, повтор пересоздаст процесс.

- [ ] **Step 5: Прогнать ВСЕ тесты**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest -v`
Expected: все unit + integration зелёные.

- [ ] **Step 6: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/app/rapfi/adapter.py backend/tests/integration
git -C /Users/alexey/code/Renju commit -m "feat(rapfi): adapter facade with reinit, wall-clock kill, respawn+retry"
```

---

### Task 14: Консольная игра `play_cli.py` (ручной smoke)

Живая проверка всего стека этапа: адаптер + домен + фолы + исходы. Не тестируем автоматикой сверх запуска `--help` — это инструмент для рук.

**Files:**
- Create: `backend/scripts/play_cli.py`
- Test: `backend/tests/unit/test_play_cli.py` (только smoke: модуль импортируется, парсер ввода работает)

- [ ] **Step 1: Написать падающий smoke-тест**

`backend/tests/unit/test_play_cli.py`:

```python
from scripts.play_cli import parse_input, render_board


def test_parse_input_letter_number():
    assert parse_input("h8") == (7, 7)
    assert parse_input("a1") == (0, 0)
    assert parse_input("o15") == (14, 14)
    assert parse_input("H8") == (7, 7)


def test_parse_input_invalid():
    for bad in ["", "z9", "h16", "h0", "88", "undo"]:
        assert parse_input(bad) is None


def test_render_board_smoke():
    out = render_board(moves=[(7, 7), (8, 8)], forbidden=[(0, 0)])
    assert "●" in out and "○" in out and "×" in out
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_play_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts'`.

- [ ] **Step 3: Реализовать `backend/scripts/play_cli.py`**

Создай также пустой `backend/scripts/__init__.py`.

```python
"""Консольная партия против Rapfi через наш адаптер. Ручной smoke этапа 1.

Запуск:  cd backend && uv run python -m scripts.play_cli --level medium
Ввод:    ход — буква+число (h8); u — undo; q — выход.
"""

import argparse
import asyncio
import random
import string

from app.config import REPO_ROOT, Settings
from app.domain.game import undo_truncate, validate_human_move
from app.domain.levels import LEVELS, Level
from app.domain.rules import outcome_after
from app.domain.values import (
    BOARD_SIZE,
    Color,
    DomainError,
    GameStatus,
    Point,
    color_to_move,
)
from app.rapfi.adapter import RapfiAdapter

_COLS = string.ascii_lowercase[:BOARD_SIZE]  # a..o


def parse_input(raw: str) -> Point | None:
    s = raw.strip().lower()
    if len(s) < 2 or s[0] not in _COLS or not s[1:].isdigit():
        return None
    x = _COLS.index(s[0])
    y = int(s[1:]) - 1
    if not (0 <= y < BOARD_SIZE):
        return None
    return (x, y)


def render_board(*, moves: list[Point], forbidden: list[Point]) -> str:
    stones: dict[Point, str] = {}
    for i, p in enumerate(moves):
        stones[p] = "●" if i % 2 == 0 else "○"
    for p in forbidden:
        stones.setdefault(p, "×")
    rows = []
    for y in range(BOARD_SIZE - 1, -1, -1):
        cells = " ".join(stones.get((x, y), "·") for x in range(BOARD_SIZE))
        rows.append(f"{y + 1:>2} {cells}")
    rows.append("   " + " ".join(_COLS))
    return "\n".join(rows)


async def game_loop(level: Level) -> None:
    settings = Settings()
    adapter = RapfiAdapter(
        bin_path=settings.resolved_rapfi_bin(),
        config_path=settings.rapfi_config,
        cwd=REPO_ROOT,
    )
    params = LEVELS[level]
    human = random.choice([Color.BLACK, Color.WHITE])
    print(f"Уровень: {level.value}. Ты играешь {'чёрными ●' if human is Color.BLACK else 'белыми ○'}.")
    moves: list[Point] = []
    try:
        while True:
            if color_to_move(len(moves)) is not human:
                print("… соперник думает")
                engine_move = await adapter.compute_move(moves, params)
                moves.append(engine_move)
                outcome = outcome_after(moves)
                if outcome is not None:
                    print(render_board(moves=moves, forbidden=[]))
                    print(f"Партия окончена: {outcome.value}")
                    return
                continue

            forbidden = (
                await adapter.forbidden_points(moves) if human is Color.BLACK else []
            )
            print(render_board(moves=moves, forbidden=forbidden))
            raw = input("Твой ход (h8 / u / q): ")
            if raw.strip().lower() == "q":
                return
            if raw.strip().lower() == "u":
                try:
                    moves = undo_truncate(moves=moves, human_color=human)
                except DomainError as e:
                    print(f"Undo нельзя: {e}")
                continue
            point = parse_input(raw)
            if point is None:
                print("Не понял. Пример: h8")
                continue
            try:
                validate_human_move(
                    moves=moves,
                    human_color=human,
                    status=GameStatus.AWAITING_HUMAN,
                    point=point,
                    forbidden=forbidden,
                )
            except DomainError as e:
                print(f"Ход отвергнут: {e}")
                continue
            moves.append(point)
            outcome = outcome_after(moves)
            if outcome is not None:
                print(render_board(moves=moves, forbidden=[]))
                print(f"Партия окончена: {outcome.value}")
                return
    finally:
        await adapter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Партия против Rapfi в терминале")
    parser.add_argument(
        "--level", choices=[lv.value for lv in Level], default=Level.MEDIUM.value
    )
    args = parser.parse_args()
    asyncio.run(game_loop(Level(args.level)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Прогнать smoke-тест**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest tests/unit/test_play_cli.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Ручной smoke (исполнителю — короткая партия)**

Run: `cd /Users/alexey/code/Renju/backend && uv run python -m scripts.play_cli --level novice`
Expected: доска рисуется; ходы принимаются; движок отвечает; при игре чёрными запрещённые точки видны как `×` и ход в них отвергается; `u` откатывает пару ходов; `q` выходит без traceback.

- [ ] **Step 6: Commit**

```bash
git -C /Users/alexey/code/Renju add backend/scripts backend/tests/unit/test_play_cli.py
git -C /Users/alexey/code/Renju commit -m "feat(cli): terminal game against engine for manual smoke testing"
```

---

### Task 15: Финал этапа — полный прогон, линт, фиксация

**Files:**
- Possibly modify: всё, что подсветит ruff

- [ ] **Step 1: Полный тестовый прогон**

Run: `cd /Users/alexey/code/Renju/backend && uv run pytest -v`
Expected: все тесты зелёные (unit — 64, integration — 12; самый долгий — hang-тест, ~15 с).

- [ ] **Step 2: Линт**

Run: `cd /Users/alexey/code/Renju/backend && uv run ruff check app tests scripts && uv run ruff format --check app tests scripts`
Expected: чисто. Если format жалуется — `uv run ruff format app tests scripts` и перепрогнать тесты.

- [ ] **Step 3: Commit (если линт что-то поправил)**

```bash
git -C /Users/alexey/code/Renju add backend
git -C /Users/alexey/code/Renju commit -m "chore(backend): ruff lint/format pass"
```

- [ ] **Step 4: Сверка с целью этапа**

Чек-лист готовности этапа 1:
- `uv run pytest` зелёный целиком (включая интеграцию с живым движком);
- `git status` чистый; локальный клон `engine/rapfi` стоит на пине `3aedf3a2…` (`git -C engine/rapfi rev-parse HEAD`);
- `uv run python -m scripts.play_cli` — партия играется руками, фолы подсвечиваются, undo работает;
- `git ls-files engine` — ровно три файла: `config.toml`, `build.sh`, `RUNBOOK.md`; сам движок, бинарь и веса — НЕ в git.

---

## Что сознательно НЕ в этом этапе

- HTTP/FastAPI, БД/SQLAlchemy/Alembic, auth — этап 2.
- SSE-хаб, игровые эндпоинты, сервисы поверх адаптера — этап 3.
- Фронт/PWA — этап 4.
- `INFO show_detail` / оценка позиции / YXNBEST — пригодится Claude-тренеру (вне MVP, спек §12).
- Калибровка чисел STRENGTH по уровням — после живой игры (спек §4.5 это допускает).
