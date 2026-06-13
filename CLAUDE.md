# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Что это

Self-hosted веб-рэндзю (профессиональные «пять в ряд», 15×15, фолы для чёрных) на
движке Rapfi. Источник истины дизайна — `docs/superpowers/specs/2026-06-07-renju-design.md`.
Разработка идёт этапами; этап 1 (бэкенд-скелет: домен + адаптер движка + CLI) уже в `main`.

## Рабочий флоу

- **Процесс задаёт скилл `renju-workflow`** — активируй его (Skill tool) на любой
  разработческой работе (фича/баг/рефакторинг/bd-задача). Кратко: спека → ревью →
  план → ревью → feature-ветка → TDD → реализация → ручное тестирование → коммит →
  ревью кода → фиксы → мерж/пуш по явной команде. **Все findings показывать без
  фильтрации**, решение приоритета — за Alexey.
- **Задачи — в beads (bd):** `bd ready` / `bd create` / `bd update <id> --claim` /
  `bd close <id>`. bd — ЧИСТЫЙ трекер. Его предписания «как работать» (session-close
  протокол, запреты на TaskCreate/MEMORY.md) НЕ применяем — процесс задаёт `renju-workflow`.
- Не работать в `main`; мерж и пуш — только по явной команде Alexey («мержи», «пуш»).

## Команды

Backend (Python 3.13 / uv), из `backend/`:
- `uv sync` — окружение.
- `uv run pytest -q` — все тесты (unit + integration против живого движка, ~6с).
- `uv run pytest tests/unit/test_rules.py::test_black_five_horizontal_wins -v` — один тест.
- `uv run ruff check app tests scripts` · `uv run ruff format app tests scripts` — линт/формат.
- `uv run python -m scripts.play_cli --level novice` — консольная партия против движка
  (ручной smoke; уровни novice…master; ход `h8`, `u` undo, `q` выход).
- **pytest гонять последовательно, не параллельно** — shared state (один процесс Rapfi).

Движок Rapfi (вне git):
- `engine/build.sh` — пересборка под CPU хоста. Бинарь между разными CPU **не
  переносить** (SIGILL). Развёртывание с нуля — `engine/RUNBOOK.md`.

## Архитектура

Слоистый бэкенд (спека §4.9), строгая изоляция:
- `app/domain/` — **чистая логика без I/O** (исходы партии, валидация хода, undo,
  уровни, дебютные зоны). НЕ импортирует `app.rapfi`/`app.config`. Тестируется юнитами.
- `app/rapfi/` — **адаптер движка**, роли разделены по файлам: `protocol.py` (pure:
  сборка команд + парсинг строк), `process.py` (OS-процесс на asyncio, без логики
  протокола), `adapter.py` (фасад `compute_move`/`forbidden_points`: владеет процессом,
  `asyncio.Lock` лимит расчётов=1, переинициализация на каждый запрос, wall-clock kill
  + respawn + retry-once).
- `app/config.py` — настройки (pydantic-settings, env `RENJU_*`).
- HTTP/FastAPI, БД/SQLite+Alembic, SSE, фронт/PWA — этапы 2–4 (ещё нет).

Движок:
- Внешний GPL-код, **вне git** (`.gitignore: /engine/rapfi/`). В git только наши
  `engine/{config.toml,build.sh,RUNBOOK.md}`.
- Протокол Piskvork/yx (stdin/stdout, текст): `START 15`→`OK`; `INFO rule 4` (рэндзю)
  + `INFO strength/timeout_turn`; `BOARD x,y,who…DONE` → ход `x,y` (who: `1`=сторона-на-
  ходу, `2`=соперник, камни в порядке ходов); `YXSHOWFORBID`→`FORBID 0707.` (фолы
  чёрных, пары `%02d%02d`, x-первым); `YXBLOCK …DONE` ограничивает зону хода движка.
- `config.toml`: `coord_conversion_mode="none"` (на это рассчитан парсер), NNUE-веса
  mix9svq, пути весов относительно каталога конфига.

## Что не очевидно

- **Исходы и дебют считаем сами** — Rapfi их не отдаёт. Чёрные выигрывают РОВНО
  пятёркой (оверлайн — не победа), белые — пятёркой и длиннее, ничья — полная доска.
- **Rapfi НЕ соблюдает дебютные правила RIF** (`RULE 4` = renju + freeopen, проверено
  в исходниках/прогонами; движок-чёрный сам ходит нелегально). Дебют (1-й в центр,
  2-й в 3×3, 3-й в 5×5) — наш домен + `YXBLOCK`-обуздание ИИ (спека §4.10).
- `levels.py` числа strength/timeout — **предварительные**, калибруются на живой игре
  (§4.5; планируется временный admin-UI).
- **Логи — в stdout** (на сервере journald под systemd пишет/ротирует; файловую
  ротацию в приложении НЕ делаем). Конфиг — `logging.basicConfig` в `create_app`.
  Пользовательские данные в логах ОБЯЗАТЕЛЬНО оборачивать `app.logging_utils.safe()`
  (CWE-117, log injection). Отклонённые операции логируем на `WARNING`.
