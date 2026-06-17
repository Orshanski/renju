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
  протокола), `adapter.py` (хелперы: `EngineError`, `_move_commands`,
  `incremental_move_commands`, `_zone_block`, константы), `registry.py` (реестр
  процессов по game_id: `EngineRegistry`, wall-clock kill + respawn + retry-once,
  инкрементальный TAKEBACK/TURN путь).
- `app/config.py` — настройки (pydantic-settings, env `RENJU_*`).
- HTTP/FastAPI (роутеры), БД/SQLite+Alembic, SSE, auth (JWT-cookie + `token_epoch`),
  фронт React/Vite + PWA — **РЕАЛИЗОВАНЫ** (релизы v1.x; настройки, админка). Фронт доставляет
  бэк (StaticFiles→`dist/`); Vite — только бандлер/тест-раннер, без dev-сервера.

Фронт (`frontend/`, React/TS/Vite, CSS Modules + @value-токены из `src/styles/tokens.module.css`):
- **Единый визуальный слой — `src/styles/layout.module.css`.** Рамка/типографика/кнопка
  (`wrap` 1120 / `eyebrow` / `title` / `sub` / `btn`) живут ТАМ; экраны подтягивают через CSS
  `composes`, НЕ переопределяют. **Одинаковые элементы = ОДИН источник** (общий модуль или React-
  компонент), НЕ копии по экранам — копии дают дрейф (вся боль v1.2.0 была про это). Изоляция
  ответственности + компонентность — требование Alexey с начала. Остаток дублей (toggle/field/
  modal/card/setrow/варианты кнопки) → в компоненты, задача **rj-rga**. Табы намеренно разные — не сводить.
- CSP — в приложении (`middleware/security_headers.py`); nginx на проде CSP НЕ дублировать
  (два заголовка → пересечение режет шрифты; ловили). `index.html` — без долгого кеша.

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
- **Дебют RIF (1-й центр, 2-й в 3×3, 3-й в 5×5) — наш домен** (`RULE 4` = renju +
  freeopen, RIF-зоны Rapfi не гарантирует). `YXBLOCK`-обуздание хода ИИ накладываем
  ТОЛЬКО на **белый 2-й ход** (3×3): сам движок туда попадает лишь ~40% (raw-замер),
  а `YXBLOCK` там безопасен (держит 100/100). На **чёрный 3-й ход зону НЕ накладываем**:
  движок сам кладёт в 5×5 ~99%, а `YXBLOCK` на этом ходу **ЛОМАЕТ** движок — слив 100/100
  (raw-прогоны живого движка, `backend/scripts/engine_probes/`). NB: механизм поломки
  точно НЕ установлен — прежнее объяснение «гасит TT-отсечки в корне» **оказалось неверным**
  (`search.cpp:1372/1466` — про не-запись корня в TT/дебютную БД, не про отсечки).
  На редкий выход чёрного 3-го вне 5×5 (~1/100) не рубим (`engine_move`: len==1 → зона). См. rj-lkx.
- **Серверная валидация хода человека — только ЦЕЛОСТНОСТЬ** (геометрия/занятость;
  `domain.validate_move`). Дебютную зону и фолы НЕ сторожим: фронт ограничивает выбор
  клеток, движок фолы соблюдает сам. Зона (`opening_zone`) и фолы (`forbidden`) живут как
  **ПОСТАВЩИКИ** ограничений фронту, не как вахтёр. Серверный сторож был бы защитой от
  несуществующей угрозы (self-hosted, свои, нет PvP/ставок — подделка хода вредит лишь себе).
- `levels.py` числа strength/timeout — **предварительные**, калибруются на живой игре
  (§4.5; планируется временный admin-UI).
- **Логи — в stdout** (на сервере journald под systemd пишет/ротирует; файловую
  ротацию в приложении НЕ делаем). Конфиг — `logging.basicConfig` в `create_app`.
  Пользовательские данные в логах ОБЯЗАТЕЛЬНО оборачивать `app.logging_utils.safe()`
  (CWE-117, log injection). Отклонённые операции логируем на `WARNING`.
- **Деплой катит миграции.** `.github/workflows/deploy.yml` делает `uv run alembic upgrade head`
  перед рестартом — смерженная миграция доезжает до прода ТОЛЬКО через этот шаг, не удалять
  (без него — 500 на новых колонках; ловили на `user_settings_v2`). Деплой: push в `main` →
  Actions (`git reset --hard` → `uv sync` → alembic → `vite build` → `systemctl restart renju`).
- **Прод НЕ долбить автоматизированными пробами** (curl, повторные запросы). Renju живёт на
  сервере Librarium (за Cloudflare; общий `fail2ban`-jail `librarium-scan` банит IP за скан/
  повторные неавторизованные `401`). curl-пробами по проду забанили IP Alexey. Для проверок —
  локальный прогон/браузер, не пулемёт по живому домену.
