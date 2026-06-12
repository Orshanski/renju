# Этап 2 (срез 2): HTTP игровой контур — async/SSE, фасад Player

- **Дата:** 2026-06-11 (пересмотрено 2026-06-12 под реальный фундамент среза 1)
- **Статус:** на ревью. Садится поверх **сделанного среза 1** (`rj-a4k` смержён: пользователь+auth+БД — спека `2026-06-11-user-auth-foundation-design.md`). Поэтому: `current_user` **реальный** (JWT-cookie из среза 1), `GameRepository` **сразу на SQLite/ORM** (без стадирования in-memory), `controllers` ссылаются на живые `user_id`, движок Rapfi въезжает в lifespan. Ядро — фасад `Player`, `advance`, async-SSE-контракт, нейтральность (no-role-coupling) — без изменений.
- **Durability (решение A, согл. Alexey):** партии durable в SQLite; `opponent_thinking` после рестарта **доигрывается пересчётом** (§4.8: позиция в БД, Rapfi stateless). Лог событий — `EventHub` **in-memory** за швом; durable `sse_events` (реплей через рестарт) — **аддитив потом**, контракт не меняет. Реконнект сейчас: `reset` → `GET /api/games/{id}` → переподписка.
- **bd:** `rj-5c9` (game-эндпоинты + SSE) + `rj-8sc` (статус-машина/очередь — поглощается). durable `sse_events` + PvP-матчмейкинг + per-user undo-настройки — отдельно (см. «Что НЕ»).
- **Дополняет:** основную спеку §4.3/4.4/4.6/4.8/4.9, дебют-спеку (preset-модель), levels-config-спеку.

## Проблема

Этап 1 дал чистый домен + адаптер Rapfi + `game_service` (stateless-хелперы) + CLI-smoke. Партия живёт только внутри одного процесса `play_cli` в локальной переменной. Чтобы играть по сети и (позже) с фронта, нужен HTTP-слой: создать партию, сделать ход, получить ответ соперника, откатить — с состоянием, переживающим отдельные HTTP-запросы.

Два архитектурных риска, которые проектируем «один раз»:
1. **Контракт доставки хода**, который придётся переделывать с приходом durability, auth и **человека на второй стороне** (PvP). Наружу (до клиента) выходит финальный контракт; тяжёлые подсистемы садятся за швами аддитивно.
2. **Связанность с ролью.** Партия рэндзю — это две стороны (чёрные/белые). Кто ходит за сторону — движок или живой соперник — **параметр, спрятанный за фасадом**, а не ветка в коде. Правила, валидация, показ и статус-машина выводятся из ПОЗИЦИИ; «движок/человек» в них не течёт (принцип `renju-no-role-coupling`).

## Ключевой принцип: что рипплит, что прячется

- **Рипплит наружу (строим один раз, финально):** контракт доставки хода — async `202` + SSE-стрим состояния. Единственная форма, переживающая PvP: ход соперника приходит **сам** (push-событием), не в ответ на твой запрос.
- **Прячется за швом (нутро меняется без переделки наружу):**
  - **Хранилище** — за `GameRepository`. Реализация — **SQLite/ORM** (фундамент среза 1, async-сессия из `app/db/deps.py:get_session`); in-memory-impl остаётся тестовым дублёром.
  - **Лог событий** — за `EventHub`. **In-memory** pub/sub + буфер (решение A); durable `sse_events` — аддитив потом за тем же швом. Курсор — стабильный монотонный `int`.
  - **Кто ходит за сторону** — за фасадом `Player`. Сервис зовёт `players[side].take_turn(...)`, не зная, движок там или человек.
  - **Аутентификация** — `current_user` **реальный** (`Depends(current_user)` из `app/routers/auth.py`, JWT-cookie + `token_epoch`, срез 1). Уже не заглушка.

**Идентичность реальна.** Параметр «кто контролирует сторону» — `User(user_id: int)` / `Engine(level_id)`. `current_user` приходит из настоящего auth среза 1 (`CurrentUser{user_id: int, role}`); доступ к партии — `current_user.user_id` контролирует какую-то сторону. PvP (второй `User`-контролёр) — матчмейкинг отдельно; модель держит обе стороны симметрично.

## Скоуп среза

**Входит:** движок Rapfi в lifespan (расширяем `app_factory` среза 1: к БД-engine добавляется владение процессом Rapfi); `GET /api/levels` (из `levels.toml` через `levels_config`); **фасад `Player`** + спецификации контролёров + фабрика; `GameRepository` (протокол) + **SQLite/ORM-impl** (+ in-memory как тестовый дублёр); таблица `games` + Alembic-миграция; `EventHub` (интерфейс) + in-memory impl; `GameService` (оркестрация, под реальным `current_user`); статус-машина + проверка очереди хода (нейтральные статусы, поглощает `rj-8sc`); эндпоинты `POST·GET /api/games`, `GET /api/games/{id}`, `POST /api/games/{id}/move`, `/undo`, `GET /api/games/{id}/events` (SSE); базовое §4.8-восстановление (`opponent_thinking` после рестарта — пересчёт); тесты по слоям + curl-smoke против живого движка.

**Не входит** (см. отдельный раздел) — durable `sse_events` (реплей через рестарт, решение A); PvP-матчмейкинг (приглашение второго `User`); per-user undo-настройки (`GET·PUT /settings`); фронт.

## Архитектура (слои §4.9)

```
HTTP (роутеры /api/games, тонкие)
  → current_user (Depends, реальный — app/routers/auth.py) + get_session (Depends — app/db/deps.py)
  → GameService (оркестрация)
      → domain/ (чистая логика: валидация, исход, undo, дебют, статус-машина)
      → Player (фасад стороны: EnginePlayer | InteractivePlayer) — прячет «движок/соперник»
      → GameRepository (протокол; SQLite/ORM impl; in-memory — тестовый дублёр)
      → RapfiAdapter (процесс движка; в lifespan — app.state.adapter)
      → EventHub (pub/sub; in-memory impl)
```

`GameService` реально строится на чистых хелперах `game_service.py` (не дублирует): старт — `new_game()`; **любой** ход (за любую сторону) применяется через **один** путь `apply_move(moves, point, *, forbidden)` (завершённость `GAME_FINISHED` → `validate_move` → склейка; единообразная позиционная валидация, рэндзю-фол проверяется кто бы ни ходил); расчёт хода движковой стороны — `engine_move(adapter, moves, params)` (дебютная зона спрятана внутри). Домен не знает про HTTP/репо/хаб; сервис не пишет SQL и не считает правила; роутеры — только HTTP-обвязка.

**Коммит-модель (как в срезе 1):** `session_scope` (`app/db/deps.py:get_session`) — только rollback-on-error + close, **писатели коммитят явно**. Значит SQLite-`GameRepository.create/update` (и пути create/move/undo) делают `await session.commit()` после мутации; `GET`-пути не коммитят. **lifespan среза 2** расширяет `create_app` (среза 1): рядом с БД-engine — `app.state.adapter = RapfiAdapter(...)` (spawn на старте, `close` на остановке), `app.state.event_hub`, `app.state.levels`.

## Фасад игрока стороны (`Player`)

Сердце нейтральности: **за кого ходит сторона — за фасадом.**

```
class Player(Protocol):
    async def take_turn(self, moves: Sequence[Point]) -> Point | None
        # Ход ЭТОЙ стороны для позиции, или None — если ход придёт извне (подачей).

EnginePlayer(adapter, params: EngineParams):
    take_turn → await engine_move(adapter, moves, params)   # Point; дебютная зона внутри
InteractivePlayer(user_id: int):
    take_turn → None                                        # ход подаётся POST'ом от user_id
```

`GameService` зовёт `players[side].take_turn(moves)` и **никогда не спрашивает «движок это или соперник»**: фасад либо отдаёт ход (сервер сам сходил), либо `None` (ждём подачу). Единственное место, где известны конкретные виды, — маленькая **фабрика** «спецификация контролёра → `Player`»: `Engine(level_id)` → `EnginePlayer(adapter, params)`, `User(user_id)` → `InteractivePlayer(user_id)`. Везде дальше — только фасад.

## Модель партии (таблица `games`, за `GameRepository`)

ORM-модель `Game` (срез 1 дал `app/db/base.py:Base`; паттерн `app/models/user.py`). Таблица `games`:
```
id            TEXT PK            # uuid4 (партии не автоинкрементны — генерим в сервисе)
owner_id      INTEGER NOT NULL   # FK → users.id (создатель; для list_by_owner)
controllers   JSON NOT NULL      # {"black": <ctl>, "white": <ctl>}; <ctl> см. ниже
moves         JSON NOT NULL      # [[x,y]…]; стартует [[7,7]] (preset, ход 1 чёрных)
status        TEXT NOT NULL      # GameStatus: awaiting_move|opponent_thinking|finished_*
undo_count    INTEGER NOT NULL DEFAULT 0
forbidden_log JSON NOT NULL DEFAULT '{}'  # МЕМО-лог фолов: dict {str(len(moves)): [фолы]}.
                                          #   ключ есть ⇔ позиция посчитана (со [] = без фолов;
                                          #   нет ключа = не посещена); непусто только на ход чёрных
created_at / updated_at  DATETIME
```
Alembic-миграция `games` (как `users` в срезе 1): `alembic/env.py` дополнительно импортирует `app.models.game` (рядом с `import app.models.user` — наполнить `Base.metadata` для autogenerate/теста); FK `owner_id→users.id` задаётся **в самом `create_table`** (не отдельным ALTER); `foreign_keys=ON` уже в прагмах `make_engine`. `controllers` — **данные** контролёра каждой стороны (сериализуемо): `{"kind":"engine","level_id":<str>}` или `{"kind":"user","user_id":<int>}`. Обе стороны независимы и симметричны: обе user (PvP), обе engine (EvE), смешанно. Уровень — ВНУТРИ engine-контролёра; у партии нет глобального движка/уровня. `is_engine(side)` нужен сервису ровно в двух местах оркестрации (показ статуса/доступ), в игровой контур не течёт — там фасад `Player`, собираемый **фабрикой** из `controllers[side]` + `app.state.adapter`.

`GameRepository` (протокол): `create(game)`, `get(game_id) -> Game | None`, `list_by_owner(owner_id) -> list[Game]`, `update(game)`. **SQLite/ORM-impl** (запросы как `app/dal/users.py`); **писатели коммитят явно** (`create`/`update` → `await session.commit()`, т.к. `session_scope` не коммитит). In-memory-impl (`dict`) — тестовый дублёр. Фильтрация/доступ — в сервисе, репо не авторизует.

**Мемо-лог `forbidden_log` (фолы по позициям).** Фол — **вызов движка** `await adapter.forbidden_points(moves)` (`app/rapfi/adapter.py`, под `asyncio.Lock`; непусто только на ход чёрных) — доменной функции нет. Доступ — мемоизированный `fouls(game, moves)`: ключ `str(len(moves))` есть в `forbidden_log` — вернуть значение (пусть даже `[]`); нет ключа — посчитать движком и **записать**. Поэтому engine-вызов за фолами случается **ровно один раз на чёрную позицию** — в `advance` (фон, при ходе вперёд). **GET, валидация подачи (`apply_move(..., forbidden=fouls)`) и undo читают лог — без захода в движок.** `GET` после рестарта берёт фолы из БД. **Undo — чистый replay:** `moves`→`moves[:k]`, из `forbidden_log` выбросить ключи `> k`; текущие фолы = `forbidden_log[str(k)]` (уже записан), движок не нужен.

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
- подающий **контролирует сторону-на-ходу**: `controllers[color_to_move(len(moves))]` — `user`-контролёр с `user_id == current_user.user_id` (иначе `NOT_YOUR_TURN` → 422; движковая или чужая сторона тоже сюда).

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
        fb = await fouls(game, moves) if side is BLACK else []   # мемо: 1-й раз — движок, пишет forbidden_log
        if fb: событие forbidden
        событие status; STOP
    status = opponent_thinking; событие status      # сервер считает server-driven сторону
    mv = await players[side].take_turn(moves)       # ФАСАД: движок посчитает; (для PvP сюда не входим)
    fb = await fouls(game, moves) if side is BLACK else []   # мемо-фолы (forbidden_log) — единообразная валидация
    moves = apply_move(moves=moves, point=mv, forbidden=fb)
    save; событие move (by = color_of_move(move_index)); continue
```

Покрывает: первый ход при создании, серию движковых ходов (EvE — доигрывает обе стороны), мгновенный возврат хода интерактивной стороне (PvP — `advance` сам не ходит, ждёт подачу соперника, чей ход прилетит SSE-событием). `is_engine(side)` здесь — выбор «сервер двигает сам или ждёт подачу», статус-семантика; сам ход берётся фасадом. **Ошибка движка** (`EngineError` после ретрая) → событие `error` (HTTP-ответа нет — `advance` фоновая), `status` остаётся `opponent_thinking`; клиент видит ошибку событием. **§4.8-восстановление (решение A):** партия durable → застрявший `opponent_thinking` (краш движка/рестарт — фоновая `advance`-задача умерла с процессом) **доигрывается пересчётом**: при обращении к партии (`GET`) в статусе `opponent_thinking` без активной фоновой задачи сервис заново запускает `advance` (идемпотентно — позиция в БД, Rapfi stateless).

### Создание — `POST /api/games { opponent }`
`opponent` задаёт контролёра **второй** стороны — параметр, не предположение. В срезе поддержан `{ kind: "engine", levelId }`; форма аддитивно расширяется на `{ kind: "user", userId }` (PvP) — логика назначения от вида не зависит.
1. `current_user` → создатель. Для `kind == "engine"` валидировать `levelId` против `levels.toml` (неизвестный → `BadInputError`→400, единая модель ошибок среза 1).
2. Назначить контролёров: создателю — **случайная** сторона (§4.6, выбора нет) как `{kind:"user", user_id: current_user.user_id}`, второй — из `opponent` (`{kind:"engine", level_id}`; позже user). `moves = [CENTER]`; `status = awaiting_move`; `forbidden_log = {}`.
3. Сохранить. **`cursor` для ответа снять ЗДЕСЬ — до `advance`** (события `advance` получат `seq > cursor`, реплей их догонит; гонки create→подписка нет).
4. Вызвать `advance` (ход 2 за движковой стороной → сервер сходит; за интерактивной → ждём подачу её контролёра). Позиционно + по контролёру.
5. Ответ — состояние партии с `cursor` из шага 3.

### Подача хода — `POST /api/games/{id}/move { x, y }` → `202`
Эндпоинт — «ход» (любой стороны), не «ход человека». Подаёт `User`-контролёр стороны-на-ходу: в HvE — создатель; в PvP — тот из двух игроков, чья очередь. Код «человека» не различает, только контролёра.
1. `current_user` → загрузить партию; доступ — контролирует сторону (иначе 404).
2. Очередь: `status == awaiting_move` (иначе `OPPONENT_THINKING` → 409) и `controllers[color_to_move(len(moves))]` — это `user`-контролёр с `user_id == current_user.user_id` (иначе `NOT_YOUR_TURN` → 422; движковая или чужая сторона тоже сюда).
3. `moves = apply_move(moves=moves, point=point, forbidden=forbidden_log[len(moves)])` — завершённость (`GAME_FINISHED`, защитно) → `validate_move` → склейка. Фолы — **из `forbidden_log`** (записан `advance`'ом при входе в эту `awaiting_move`-позицию), **без вызова движка**. `MoveRejected` → код по причине (занятость/геометрия/фол/дебют → 422).
4. Сохранить. **Событие `move`** (`by = color_of_move(move_index)`, позиционно).
5. `outcome_after(moves)`: кончилась → `status = finished_*` + событие `status`, `202`. Иначе → `advance` (сама поставит `opponent_thinking` и сходит за движковые стороны либо отдаст ход интерактивной), `202`. Курсор-гонки нет: клиент уже подписан, события по порядку `seq`.

### Undo — `POST /api/games/{id}/undo` → `200` + состояние
1. `current_user` → загрузить партию; доступ — контролирует сторону (иначе 404).
2. `check_undo(policy=UndoPolicy(), status=game.status, undo_count=game.undo_count)` (домен, существует). С дефолтной `UndoPolicy()` реально может бросить только `OPPONENT_THINKING` (сервер считает) → 409. `UndoRejected` → код по причине.
3. `undo_truncate(moves=moves, for_color=<сторона, которой управляет current_user>)` (домен). Нечего откатывать → `NOTHING_TO_UNDO` → 422.
4. **`moves`→`moves[:k]`; из `forbidden_log` выбросить ключи `> k`** (replay лога), `undo_count += 1`, `status = awaiting_move`, сохранить (commit). Текущие фолы = `forbidden_log[str(k)]` — уже записан (позиция пройдена вперёд). **Событие `undo`** (усечение) + при непустом фоле **событие `forbidden`** + новое состояние в ответе.
5. Undo **честно без движка**: фолы берутся из лога, не пересчитываются. Усечение видят и ответ, и SSE-событие (другие устройства/PvP).

> **Undo-политика.** Доменные `check_undo` + `UndoPolicy(enabled, limit, after_game_end)` (`undo.py`) **уже есть**. В срезе — дефолтная `UndoPolicy()` (разрешён, без лимита, после конца партии тоже). Per-user **значения** (хранение/`GET·PUT /settings`) — с auth+durability; здесь не персистим.

## Контракт SSE и модель событий

`GET /api/games/{id}/events?since=<cursor>`:
1. `current_user`; доступ — контролирует сторону.
2. Подписаться на `EventHub` по `game_id`. Реплей событий с `seq > since` из буфера, затем live.
3. Курсор недостижим → управляющее `event: reset` (клиент перезапрашивает `GET /api/games/{id}` и переподписывается). В in-memory срезе буфер хранит партию целиком (≤ пара сотен событий, не усекается), поэтому реально срабатывает только верхняя граница (`since > текущего seq` — «курсор из будущего»). Усечение снизу — шов под durable-impl (там буфер ограничен).
4. Heartbeat-пинг (`:`-комментарий) каждые `sse_heartbeat_s` (дефолт **15с**); на каждом heartbeat **перепроверять `token_epoch`** (`fetch_token_epoch` на **свежей короткой сессии** из `app.state.sessionmaker` — request-сессию `get_session` НЕ держим открытой весь долгоживущий стрим): отозван (epoch не совпал) → закрыть стрим (§4.4). Заголовок `X-Accel-Buffering: no`. На разрыве — отписка. (Мгновенный teardown-реестр на бампе epoch — позже; здесь достаточно проверки на heartbeat.)

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
`controllers` — вид контролёра каждой стороны (id чужого игрока не светим). `your_color` — сторона, которой управляет запросивший `User` (для рендера «ты за чёрных/белых»); выводится из контролёров + `current_user`, позиционно. Нет глобального `level_id`/`human_color`. `cursor` — текущий `seq` (клиент сразу подписывается `?since=cursor`). `forbidden` (= `forbidden_log[len(moves)]`) — текущие фолы, непусто только на ходу чёрных.

## Идентичность (реальный auth среза 1)

Все `/api/games*` — под **реальным** `Depends(current_user)` (`app/routers/auth.py`: JWT-cookie → `decode_token` → `token_epoch`-сверка с БД). `current_user: CurrentUser{user_id: int, role}`. Нет cookie / невалид / отозван → 401 (как `/api/auth/me`). Доступ к конкретной партии: `current_user.user_id` совпадает с `user_id` какого-то `User`-контролёра партии (иначе **404** — скрываем существование). CSRF (`X-Requested-With` на небезопасных `/api/`) и security-заголовки — те же middleware среза 1; SSE — GET, под CSRF не попадает. Заглушки/`X-Dev-User` нет.

## Обработка ошибок

- `OPPONENT_THINKING` (подача/undo во время серверного расчёта) → **409** (конфликт состояния).
- Прочие `MoveRejected` (`NOT_YOUR_TURN`/занятость/геометрия/фол/дебют/`GAME_FINISHED`) и `UndoRejected.NOTHING_TO_UNDO` → **422** с машинной причиной (enum-строка).
- Партия не найдена / нет доступа → **404** (скрываем существование).
- Неизвестный `levelId` → **400** (`BadInputError`, единая модель ошибок среза 1).
- Сбой движка: в синхронном пути его нет (расчёт фоновый) → событие `error` в SSE, не HTTP-кодом.

> **Маппинг `MoveRejected`/`UndoRejected` → HTTP — делает game-роутер** (или новый exception-handler): ветвит код по `.reason` (`OPPONENT_THINKING`→409, прочие→422). В `error_handlers._MAP` среза 1 этих доменных типов НЕТ (там только `AuthError`/`NotFoundError`/`ConflictError`/`ForbiddenError`/`RateLimitError`/`BadInputError`). А вот «нет доступа/не найдена»→404 и «неизвестный `levelId`»→400 удобнее бросать как `NotFoundError`/`BadInputError` — их `_MAP` уже покрывает.

## Конфигурация

`app/config.py` (срез 1) расширяется одним полем: `sse_heartbeat_s = 15` (интервал heartbeat SSE). Движок (`rapfi_bin` / `rapfi_config` / `engine_kill_grace_s`) и БД/auth-настройки уже есть. Через `RENJU_*` env (pydantic-settings).

## Тестирование

- **Домен** — юниты (существующие + возвращённые `NOT_YOUR_TURN`/занятость/статус-переходы).
- **Repository** — юниты против **обеих** impl: in-memory (быстрые) и SQLite/ORM на tmp-БД (create/get/list_by_owner/update). + тест **миграции `games`** (`alembic upgrade head` на tmp-БД → проверка колонок, как делали для `users` в срезе 1).
- **EventHub** — юниты: publish→seq, subscribe+реплей по курсору, `since > текущего seq` → reset.
- **Player-фабрика** — юнит: `Engine(level)` → `EnginePlayer`, `User(id)` → `InteractivePlayer`; `InteractivePlayer.take_turn → None`, `EnginePlayer.take_turn` зовёт адаптер (на фейке).
- **GameService** — юниты с in-memory-репо + **фейковым адаптером** + in-memory-хабом: создание с разными контролёрами, позиционный первый ход через `advance`, подача + автоход движковой стороны, очередь по контролёру (`NOT_YOUR_TURN`/`OPPONENT_THINKING`), undo + событие `forbidden`. **Тест нейтральности (обязателен):** обе стороны `User` (PvP-форма) — `advance` сам НЕ ходит, ждёт подачу второго игрока, его ход доходит SSE-событием; обе `Engine` (EvE) — `advance` доигрывает. Доказывает, что контур не зашит на «один человек + один движок» и что на второй стороне может быть человек.
- **API** — `httpx.AsyncClient`/FastAPI test client с фейковым адаптером: эндпоинты, коды (409/422/404), доступ по контролёру, SSE отдаёт события.
- **Integration** — минимум против живого движка (создать vs Engine, сделать ход, дождаться реального ответа), **последовательно** (shared Rapfi).
- **Ручной smoke (Alexey, шаг 10)** — curl партии против живого движка: создать, ходить, видеть ответ событием, undo. Не автоматизируем.

## Карта на bd

- **Этот срез = `rj-5c9`** (игровые эндпоинты + SSE) **+ `rj-8sc`** (статус-машина/очередь + нейтральный rename статусов) — поглощается сюда.
- Опирается на смержённый **`rj-a4k`** (срез 1: FastAPI-каркас + БД/Alembic + auth).
- Новыми тикетами (отдельно, см. «Что НЕ»): durable `sse_events`; PvP-матчмейкинг; per-user undo-настройки (`/settings`).

Точную перекройку bd — после утверждения спеки (claim перед кодом).

## Что НЕ в этом срезе (scope-забор — не предлагать как findings)

> Срез 1 (`rj-a4k`) уже дал БД/Alembic + реальный auth + каркас — это **не** откладывается, оно используется. Отложено только перечисленное ниже.

- **Durable `sse_events` (реплей событий через рестарт, решение A):** лог `EventHub` — in-memory; durable-таблица + reconnect-by-cursor через рестарт — аддитив потом за тем же швом. (Партии durable, базовое §4.8-восстановление пересчётом — ЕСТЬ; durable-SSE НЕ выносить как недостаток.)
- **Мгновенный teardown SSE-стримов на бампе epoch** (in-process реестр, §4.4) — здесь стрим перепроверяет epoch на heartbeat и закрывается при отзыве (этого достаточно); активный реестр-разрыв — позже.
- **PvP-матчмейкинг:** приглашение/подключение второго `User`-игрока, листинг по участию, выбор цвета. Модель/контур уже держат (обе стороны симметричны), но создание «человек vs человек» и его UX — отдельно. Здесь `opponent` поддерживает только `kind:"engine"`.
- **Per-user undo-настройки** (`GET·PUT /settings`, таблица `user_settings`) — здесь дефолтная `UndoPolicy()`.
- **Admin-морда / engine-config admin** — позже (§4.7, `rj-tan`).
- **Фронт/PWA** — Этап 4 (`rj-8wf`).
- **Мультиворкер / Postgres** — вне MVP (§3, один воркер-владелец).
- **Семантика undo в PvP** (что откатывать, когда обе стороны — `User`) — будущее; здесь undo от стороны, которой управляет запросивший.
