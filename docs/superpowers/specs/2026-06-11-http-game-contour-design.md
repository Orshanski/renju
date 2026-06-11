# Этап 2 (срез 2): HTTP игровой контур — async/SSE, фасад Player

- **Дата:** 2026-06-11
- **Статус:** дизайн среза 2 — **РЕСЕКВЕНИРОВАН: идёт ПОСЛЕ среза 1** (фундамент пользователь+auth+БД, спека `2026-06-11-user-auth-foundation-design.md`). При переходе к реализации пересматривается: партии сразу в БД (уходит стадирование in-memory→SQLite за `GameRepository`), `current_user` реальный, `controllers` ссылаются на живые `user_id`. Фасад `Player`/`advance`/async-SSE-контракт и нейтральность (no-role-coupling) остаются. (Ниже по тексту «in-memory сейчас» читать как «к пересмотру».)
- **bd:** перекраивает `rj-a4k` (HTTP-каркас) + игровую часть `rj-5c9` (game-эндпоинты + SSE) + `rj-8sc` (статус-машина); durability и auth выносятся отдельными срезами (см. «Что НЕ в этом срезе» и «Карта на bd»).
- **Дополняет:** основную спеку §4.3/4.4/4.6/4.8/4.9, дебют-спеку (preset-модель), levels-config-спеку.

## Проблема

Этап 1 дал чистый домен + адаптер Rapfi + `game_service` (stateless-хелперы) + CLI-smoke. Партия живёт только внутри одного процесса `play_cli` в локальной переменной. Чтобы играть по сети и (позже) с фронта, нужен HTTP-слой: создать партию, сделать ход, получить ответ соперника, откатить — с состоянием, переживающим отдельные HTTP-запросы.

Два архитектурных риска, которые проектируем «один раз»:
1. **Контракт доставки хода**, который придётся переделывать с приходом durability, auth и **человека на второй стороне** (PvP). Наружу (до клиента) выходит финальный контракт; тяжёлые подсистемы садятся за швами аддитивно.
2. **Связанность с ролью.** Партия рэндзю — это две стороны (чёрные/белые). Кто ходит за сторону — движок или живой соперник — **параметр, спрятанный за фасадом**, а не ветка в коде. Правила, валидация, показ и статус-машина выводятся из ПОЗИЦИИ; «движок/человек» в них не течёт (принцип `renju-no-role-coupling`).

## Ключевой принцип: что рипплит, что прячется

- **Рипплит наружу (строим один раз, финально):** контракт доставки хода — async `202` + SSE-стрим состояния. Единственная форма, переживающая PvP: ход соперника приходит **сам** (push-событием), не в ответ на твой запрос.
- **Прячется за швом (стадируем нутро без переделки наружу):**
  - **Хранилище** — за `GameRepository`. In-memory сейчас → SQLite потом. In-memory-реализация не выбрасывается: навсегда тестовый дублёр.
  - **Лог событий** — за `EventHub`. In-memory pub/sub + буфер сейчас → durable `sse_events` потом. Курсор — стабильный монотонный `int`.
  - **Кто ходит за сторону** — за фасадом `Player`. Сервис зовёт `players[side].take_turn(...)`, не зная, движок там или человек. Движок/соперник меняются без переписывания игрового контура.
  - **Аутентификация** — за `current_user`. Заглушка (dev-пользователь) сейчас → JWT-cookie/`token_epoch` потом.

**Идентичность ≠ аутентификация.** Параметр «кто контролирует сторону» (`User(id)`/`Engine(level)`) прошит в модель/запросы **сейчас**; откладывается только **доказательство личности** (login). Шов `current_user` уже есть → реальный auth потом — своп резолвера, а не пересборка модели.

## Скоуп среза

**Входит:** FastAPI-каркас (app-factory, конфиг, lifespan владеет процессом Rapfi, маппинг доменных ошибок в HTTP); идентичность-шов (`current_user`-заглушка, доступ по контролёру стороны); **фасад `Player`** + спецификации контролёров; `GameRepository` (протокол) + in-memory; `EventHub` (интерфейс) + in-memory; `GameService` (оркестрация); статус-машина + проверка очереди хода (нейтральные статусы, поглощает `rj-8sc`); эндпоинты `/health`, `/levels`, `POST·GET /games`, `GET /games/{id}`, `POST /games/{id}/move`, `POST /games/{id}/undo`, `GET /games/{id}/events` (SSE); тесты по слоям + ручной curl-smoke.

**Не входит** (см. отдельный раздел) — durability, реальный auth, PvP-матчмейкинг (приглашение второго игрока), per-user undo-политика, фронт.

## Архитектура (слои §4.9)

```
HTTP (роутеры, тонкие)
  → current_user (зависимость; заглушка)
  → GameService (оркестрация)
      → domain/ (чистая логика: валидация, исход, undo, дебют, статус-машина)
      → Player (фасад стороны: EnginePlayer | InteractivePlayer) — прячет «движок/соперник»
      → GameRepository (протокол; in-memory impl)
      → RapfiAdapter (процесс движка; владеет lifespan)
      → EventHub (pub/sub; in-memory impl)
```

`GameService` реально строится на чистых хелперах `game_service.py` (не дублирует): старт — `new_game()`; **любой** ход (за любую сторону) применяется через **один** путь `apply_move(moves, point, *, forbidden)` (завершённость `GAME_FINISHED` → `validate_move` → склейка; единообразная позиционная валидация, рэндзю-фол проверяется кто бы ни ходил); расчёт хода движковой стороны — `engine_move(adapter, moves, params)` (дебютная зона спрятана внутри). Домен не знает про HTTP/репо/хаб; сервис не пишет SQL и не считает правила; роутеры — только HTTP-обвязка.

## Фасад игрока стороны (`Player`)

Сердце нейтральности: **за кого ходит сторона — за фасадом.**

```
class Player(Protocol):
    async def take_turn(self, moves: Sequence[Point]) -> Point | None
        # Ход ЭТОЙ стороны для позиции, или None — если ход придёт извне (подачей).

EnginePlayer(adapter, params: EngineParams):
    take_turn → await engine_move(adapter, moves, params)   # Point; дебютная зона внутри
InteractivePlayer(user_id: str):
    take_turn → None                                        # ход подаётся POST'ом от user_id
```

`GameService` зовёт `players[side].take_turn(moves)` и **никогда не спрашивает «движок это или соперник»**: фасад либо отдаёт ход (сервер сам сходил), либо `None` (ждём подачу). Единственное место, где известны конкретные виды, — маленькая **фабрика** «спецификация контролёра → `Player`»: `Engine(level_id)` → `EnginePlayer(adapter, params)`, `User(user_id)` → `InteractivePlayer(user_id)`. Везде дальше — только фасад.

## Модель партии (in-memory, за `GameRepository`)

```
Game:
  id: str                              # uuid4
  controllers: dict[Color, Controller] # СТОРОНА → спецификация контролёра (данные, сериализуемо):
                                       #   Controller = Engine(level_id) | User(user_id).
                                       #   Обе стороны независимы и симметричны: обе User (PvP),
                                       #   обе Engine (EvE), либо смешанно. Уровень живёт ВНУТРИ
                                       #   Engine — у партии нет глобального движка/уровня.
  owner_id: str                        # создатель (для list_by_owner); доступ — контролирует любую сторону
  moves: list[Point]                   # стартует [CENTER] (preset, ход 1 чёрных)
  status: GameStatus
  undo_count: int
  forbidden: list[Point]               # КЕШ фолов; непусто только когда ход чёрных.
                                       #   Единственный источник истины о фолах в срезе.
  created_at / updated_at: datetime
```

`controllers` хранит **данные** (`Engine(level_id)` / `User(user_id)`) — сериализуемо для будущей БД; живой `Player`-фасад (с адаптером) собирается фабрикой в рантайме. `is_engine(side) := isinstance(controllers[side], Engine)` нужен сервису ровно в двух местах оркестрации (показ статуса/доступ), в игровой контур не течёт — там фасад.

`GameRepository` (протокол): `create(game)`, `get(game_id) -> Game | None`, `list_by_owner(owner_id) -> list[Game]`, `update(game)`. Реализация — `dict[str, Game]`; фильтрация и проверка доступа — в сервисе (репо не авторизует).

**Кеш `forbidden`.** Фол — функция позиции (`forbidden_points(moves)`, непусто только на ходу чёрных). Сервис считает его **один раз** при каждом переходе в `awaiting_move` с чёрными на ходу (в `advance` и после undo) и кладёт в `Game.forbidden`. Оттуда читают **оба** синхронных пути без вызова движка: `GET /games/{id}` (поле состояния) и валидация подачи (`apply_move(..., forbidden=game.forbidden)`). Так из «горячего» HTTP-пути убран синхронный вызов движка под общим `asyncio.Lock`.

## Статус-машина (нейтральная, поглощает `rj-8sc`)

Статусы (переименование из §4.3, no-role-coupling):
- `awaiting_move` — на ходу интерактивная сторона, ввод принимается (было `awaiting_human`).
- `opponent_thinking` — **сервер считает** ход движковой стороны; ввод не принимается (было `engine_thinking`; нейтрально — это «сервер занят расчётом», не «движок»).
- `finished_black` / `finished_white` / `finished_draw`.

> `opponent_thinking` означает строго «сервер вычисляет ход server-driven стороны». Ожидание хода **живого** соперника (PvP) — это `awaiting_move` (сервер ничего не считает, просто ждёт подачу); «соперник думает» там показывает клиент, выводя из `your_color ≠ color_to_move`, без серверного статуса.

Переходы: `awaiting_move → (подан ход) → [opponent_thinking → (сервер сходил за движковую сторону)] → awaiting_move → … → finished_*`. Undo из `finished_*`/`awaiting_move` → `awaiting_move`.

**Точечные изменения enum'ов в `values.py` (+потребители):**
- `GameStatus.AWAITING_HUMAN → AWAITING_MOVE`, `ENGINE_THINKING → OPPONENT_THINKING` (значения строк тоже); `FINISHED_*` без изменений.
- `UndoRejectReason.ENGINE_THINKING → OPPONENT_THINKING`.
- `MoveRejectReason`: `NOT_YOUR_TURN` уже есть (был, в `validate_move` не используется — проверка вынесена в сервис); **добавить** `OPPONENT_THINKING` (подача во время серверного расчёта) — отдельная причина от `NOT_YOUR_TURN`.
- Потребители rename: `domain/undo.py:check_undo` (сверяет `GameStatus.ENGINE_THINKING`), тесты. `outcome_after` возвращает `FINISHED_*` — не трогаем.

**Проверка очереди хода (в сервисе).** В дебюте `validate_move` стала позиционной и потеряла проверку очереди (`play_cli` гарантировал её структурой цикла). По HTTP ход приходит извне, поэтому сервис при подаче явно проверяет:
- `status == awaiting_move` (иначе `OPPONENT_THINKING` → 409),
- подающий **контролирует сторону-на-ходу**: `controllers[color_to_move(len(moves))] == User(current_user.id)` (иначе `NOT_YOUR_TURN` → 422; сюда же — попытка сходить за движковую или чужую сторону).

Проверка — позиция (`color_to_move`) + контролёр; роль не фигурирует. Возвращаются тесты на оба отказа (удалены в дебютной задаче).

## Поток хода (сердце среза)

**`advance` — единый код-путь продвижения, зовётся после ЛЮБОГО применённого хода и при создании.** Крутит партию через фасад `Player`, без ветки «движок/человек»:

```
advance(game):
  loop:
    if (o := outcome_after(moves)):          # finished_black|white|draw
        status = o; событие status; STOP
    side = color_to_move(len(moves))
    if not is_engine(side):                  # интерактивная сторона — ход придёт подачей
        status = awaiting_move
        game.forbidden = forbidden_points(moves) if side is BLACK else []
        if game.forbidden: событие forbidden
        событие status; STOP
    status = opponent_thinking; событие status      # сервер считает server-driven сторону
    mv = await players[side].take_turn(moves)       # ФАСАД: движок посчитает; (для PvP сюда не входим)
    fb = forbidden_points(moves) if side is BLACK else []   # единообразная валидация и движку
    moves = apply_move(moves=moves, point=mv, forbidden=fb)
    save; событие move (by = color_of_move(move_index)); continue
```

Покрывает: первый ход при создании, серию движковых ходов (EvE — доигрывает обе стороны), мгновенный возврат хода интерактивной стороне (PvP — `advance` сам не ходит, ждёт подачу соперника, чей ход прилетит SSE-событием). `is_engine(side)` здесь — выбор «сервер двигает сам или ждёт подачу», статус-семантика; сам ход берётся фасадом. **Ошибка движка** (`EngineError` после ретрая) → событие `error` (HTTP-ответа нет — `advance` фоновая), `status` остаётся `opponent_thinking` (в срезе без авто-восстановления; §4.8 — durability-срез); клиент видит ошибку событием.

### Создание — `POST /games { opponent }`
`opponent` задаёт контролёра **второй** стороны — параметр, не предположение. В срезе поддержан `{ kind: "engine", levelId }`; форма аддитивно расширяется на `{ kind: "user", userId }` (PvP) — логика назначения от вида не зависит.
1. `current_user` → создатель. Для `kind == "engine"` валидировать `levelId` против `levels.toml` (неизвестный → 422).
2. Назначить контролёров: создателю — **случайная** сторона (§4.6, выбора нет) как `User(current_user.id)`, второй — из `opponent` (`Engine(levelId)`; позже `User(userId)`). `moves = [CENTER]`; `status = awaiting_move`; `forbidden = []`.
3. Сохранить. **`cursor` для ответа снять ЗДЕСЬ — до `advance`** (события `advance` получат `seq > cursor`, реплей их догонит; гонки create→подписка нет).
4. Вызвать `advance` (ход 2 за движковой стороной → сервер сходит; за интерактивной → ждём подачу её контролёра). Позиционно + по контролёру.
5. Ответ — состояние партии с `cursor` из шага 3.

### Подача хода — `POST /games/{id}/move { x, y }` → `202`
Эндпоинт — «ход» (любой стороны), не «ход человека». Подаёт `User`-контролёр стороны-на-ходу: в HvE — создатель; в PvP — тот из двух игроков, чья очередь. Код «человека» не различает, только контролёра.
1. `current_user` → загрузить партию; доступ — контролирует сторону (иначе 404).
2. Очередь: `status == awaiting_move` (иначе `OPPONENT_THINKING` → 409) и `controllers[color_to_move(len(moves))] == User(current_user.id)` (иначе `NOT_YOUR_TURN` → 422).
3. `moves = apply_move(moves=moves, point=point, forbidden=game.forbidden)` — завершённость (`GAME_FINISHED`, защитно) → `validate_move` → склейка. `forbidden` из **кеша**, без вызова движка. `MoveRejected` → код по причине (занятость/геометрия/фол/дебют → 422).
4. Сохранить. **Событие `move`** (`by = color_of_move(move_index)`, позиционно).
5. `outcome_after(moves)`: кончилась → `status = finished_*` + событие `status`, `202`. Иначе → `advance` (сама поставит `opponent_thinking` и сходит за движковые стороны либо отдаст ход интерактивной), `202`. Курсор-гонки нет: клиент уже подписан, события по порядку `seq`.

### Undo — `POST /games/{id}/undo` → `200` + состояние
1. `current_user` → загрузить партию; доступ — контролирует сторону (иначе 404).
2. `check_undo(policy=UndoPolicy(), status=game.status, undo_count=game.undo_count)` (домен, существует). С дефолтной `UndoPolicy()` реально может бросить только `OPPONENT_THINKING` (сервер считает) → 409. `UndoRejected` → код по причине.
3. `undo_truncate(moves=moves, for_color=<сторона, которой управляет current_user>)` (домен). Нечего откатывать → `NOTHING_TO_UNDO` → 422.
4. Сохранить, `undo_count += 1`, `status = awaiting_move`, обновить кеш `forbidden` (на ходу чёрных — `forbidden_points(moves)`, иначе `[]`). **Событие `undo`** (усечение) + при непустом фоле **событие `forbidden`** (симметрично `advance`) + новое состояние в ответе.
5. Undo синхронный (домен, без движка): результат и в ответе, и событием (другие устройства/PvP увидят усечение).

> **Undo-политика.** Доменные `check_undo` + `UndoPolicy(enabled, limit, after_game_end)` (`undo.py`) **уже есть**. В срезе — дефолтная `UndoPolicy()` (разрешён, без лимита, после конца партии тоже). Per-user **значения** (хранение/`GET·PUT /settings`) — с auth+durability; здесь не персистим.

## Контракт SSE и модель событий

`GET /games/{id}/events?since=<cursor>`:
1. `current_user`; доступ — контролирует сторону.
2. Подписаться на `EventHub` по `game_id`. Реплей событий с `seq > since` из буфера, затем live.
3. Курсор недостижим → управляющее `event: reset` (клиент перезапрашивает `GET /games/{id}` и переподписывается). В in-memory срезе буфер хранит партию целиком (≤ пара сотен событий, не усекается), поэтому реально срабатывает только верхняя граница (`since > текущего seq` — «курсор из будущего»). Усечение снизу — шов под durable-impl (там буфер ограничен).
4. Heartbeat-пинг (`:`-комментарий) каждые `heartbeat_s` (дефолт **15с**); заголовок `X-Accel-Buffering: no`. На разрыве — отписка.

**Событие:** `{ seq: int, type, payload }`. `seq` — монотонный `int` на партию (курсор). Типы (не закрытый список, §4.6):
- `move` — `{ by: "black"|"white", point: [x,y], move_index }` (`by = color_of_move(move_index)` — позиционно, не «человек/движок»)
- `forbidden` — `{ points: [[x,y]…] }` (на ходу чёрных, подсветка)
- `status` — `{ status }`
- `undo` — `{ move_count }`
- `error` — `{ message }` (сбой серверного расчёта)
- `reset` — управляющее (курсор недостижим)

`EventHub` (интерфейс): `publish(game_id, type, payload) -> seq`, `subscribe(game_id, since) -> async iterator`. In-memory impl: per-game `asyncio`-подписчики + буфер событий (храним полностью). Durable-impl (потом) — та же сигнатура, реплей из `sse_events`.

## Форма состояния (ответ create/get)

```
{ id, owner_id,
  controllers: { black: {kind: "engine", levelId} | {kind: "user"},
                 white: {kind: "engine", levelId} | {kind: "user"} },
  your_color, status, moves: [[x,y]…], undo_count, cursor, forbidden: [[x,y]…] }
```
`controllers` — вид контролёра каждой стороны (id чужого игрока не светим). `your_color` — сторона, которой управляет запросивший `User` (для рендера «ты за чёрных/белых»); выводится из контролёров + `current_user`, позиционно. Нет глобального `level_id`/`human_color`. `cursor` — текущий `seq` (клиент сразу подписывается `?since=cursor`). `forbidden` — непусто только на ходу чёрных.

## Идентичность-шов (заглушка)

Зависимость `current_user() -> User` (`User` — минимальное value-object `{ id }`; `role` присоединится с admin/auth аддитивно). Заглушка: фиксированный `dev`-пользователь; для curl-проверки изоляции доступа (разные контролёры) — опц. заголовок `X-Dev-User: <id>`. Таблицы users **нет** (идентичность — `id`-строка). Реальный auth (потом) свопает резолвер на разбор JWT-cookie.

## Обработка ошибок

- `OPPONENT_THINKING` (подача/undo во время серверного расчёта) → **409** (конфликт состояния).
- Прочие `MoveRejected` (`NOT_YOUR_TURN`/занятость/геометрия/фол/дебют/`GAME_FINISHED`) и `UndoRejected.NOTHING_TO_UNDO` → **422** с машинной причиной (enum-строка).
- Партия не найдена / нет доступа → **404** (скрываем существование).
- Неизвестный `levelId` → **422**.
- Сбой движка: в синхронном пути его нет (расчёт фоновый) → событие `error` в SSE, не HTTP-кодом.

## Конфигурация

`app/config.py` расширяется server-настройками (host/port, `heartbeat_s=15`, dev-user-id, при необходимости CORS-origins для будущего фронта). Через `RENJU_*` env (pydantic-settings, как есть).

## Тестирование

- **Домен** — юниты (существующие + возвращённые `NOT_YOUR_TURN`/занятость/статус-переходы).
- **Repository** — юниты против in-memory impl (create/get/list_by_owner/update).
- **EventHub** — юниты: publish→seq, subscribe+реплей по курсору, `since > текущего seq` → reset.
- **Player-фабрика** — юнит: `Engine(level)` → `EnginePlayer`, `User(id)` → `InteractivePlayer`; `InteractivePlayer.take_turn → None`, `EnginePlayer.take_turn` зовёт адаптер (на фейке).
- **GameService** — юниты с in-memory-репо + **фейковым адаптером** + in-memory-хабом: создание с разными контролёрами, позиционный первый ход через `advance`, подача + автоход движковой стороны, очередь по контролёру (`NOT_YOUR_TURN`/`OPPONENT_THINKING`), undo + событие `forbidden`. **Тест нейтральности (обязателен):** обе стороны `User` (PvP-форма) — `advance` сам НЕ ходит, ждёт подачу второго игрока, его ход доходит SSE-событием; обе `Engine` (EvE) — `advance` доигрывает. Доказывает, что контур не зашит на «один человек + один движок» и что на второй стороне может быть человек.
- **API** — `httpx.AsyncClient`/FastAPI test client с фейковым адаптером: эндпоинты, коды (409/422/404), доступ по контролёру, SSE отдаёт события.
- **Integration** — минимум против живого движка (создать vs Engine, сделать ход, дождаться реального ответа), **последовательно** (shared Rapfi).
- **Ручной smoke (Alexey, шаг 10)** — curl партии против живого движка: создать, ходить, видеть ответ событием, undo. Не автоматизируем.

## Карта на bd

- `rj-a4k` — пере-скоупится: FastAPI-каркас/lifespan/идентичность-шов/фасад остаются здесь; БД/Alembic/auth **выезжают** в durability+auth-тикет.
- `rj-5c9` — игровые эндпоинты + game-часть SSE **въезжают сюда**; durable-лог/реконнект-через-рестарт — за durability.
- `rj-8sc` — статус-машина + очередь хода + нейтральный rename — **целиком сюда**.
- Новый тикет (следующий срез): **durability + real auth вместе** (SQLite/Alembic, durable `sse_events`, восстановление §4.8, JWT-cookie/`token_epoch`/users/admin/bootstrap, per-user undo-политика).

Точную перекройку bd — после утверждения спеки (claim перед кодом).

## Что НЕ в этом срезе (scope-забор — не предлагать как findings)

- **Durability:** SQLite/SQLAlchemy async/aiosqlite, Alembic/миграции, прагмы WAL/FK, durable `sse_events` + реплей через рестарт, восстановление `opponent_thinking` после краха (§4.8). За швами `GameRepository`/`EventHub`, следующий срез.
- **Реальная аутентификация:** JWT/cookie/bcrypt/`token_epoch`/login/logout/me/таблица users/admin-эндпоинты/CLI-bootstrap/teardown SSE на бампе epoch. Своп резолвера `current_user`, следующий срез.
- **PvP-матчмейкинг:** приглашение/подключение второго `User`-игрока, листинг по участию, цвет-выбор. Модель/контур уже это держат (обе стороны симметричны), но создание партии «человек vs человек» и его UX — отдельно. Здесь `opponent` поддерживает только `kind: "engine"`.
- **Per-user настройки** (undo-политика) — с auth+durability; здесь дефолт.
- **Admin-морда / engine-config admin** — позже (§4.7, `rj-tan`).
- **Фронт/PWA** — Этап 4 (`rj-8wf`).
- **Мультиворкер / Postgres** — вне MVP (§3, один воркер-владелец).
- **Семантика undo в PvP** (что откатывать, когда обе стороны — `User`) — будущее; здесь undo от стороны, которой управляет запросивший.
