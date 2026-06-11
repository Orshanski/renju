# Этап 2 (срез 1): Пользователь + авторизация — фундамент (перенос auth из librarium на ORM)

- **Дата:** 2026-06-11
- **Статус:** черновик на ревью
- **bd:** часть `rj-a4k` (FastAPI-каркас + БД + auth). Игровой контур (фасад `Player`, async/SSE, очередь хода) — **следующий** срез 2, спека `2026-06-11-http-game-contour-design.md` (она садится поверх этого фундамента: реальный `current_user`, партии в БД).
- **Дополняет:** основную спеку §4.3 (хранилище), §4.4 (пользователи/авторизация), §4.6 (контракт API), §4.9 (слои).
- **Источник переноса:** `/Users/alexey/code/librarium-py/backend/app/` — auth там проверен боем; переносим **алгоритмы** (не байт-в-байт sqlite3), на SQLAlchemy async.

## Зачем фундамент первым

Backend весь параметризуется пользователем (`ownerId` партии, доступ только владельцу, per-user настройки — §4.3/4.4). Пока пользователь — заглушка, роль протекает в код (ловили на дебюте/контуре). Поэтому строим **пользователя настоящим первым**, а игровой контур (срез 2) уже параметризуем им честно — без заглушек и ретрофита. Это два среза, переставленные местами, а не «одним куском».

## Принцип: переносим проверенное, чиним одно

- **Auth-алгоритмы librarium переносим как есть** (JWT-cookie, `token_epoch`, bcrypt, `CurrentUser`, скользящий refresh, rate-limit логина, `require_admin`, маппинг ошибок класс→статус) — реализация на SQLAlchemy async вместо сырого `sqlite3`.
- **Чиним одно: заголовки.** В librarium security-заголовки (CSP/HSTS/X-Frame-Options/…) отданы nginx. Здесь приложение **самодостаточно** — ставит их само (middleware), без завязки на конкретный reverse-proxy. CSRF-проверку (`X-Requested-With`) librarium уже делает в приложении — её тоже переносим.
- **`token_epoch` — без in-memory кеша** (см. отдельный раздел: почему librarium его завёл и почему здесь не нужен).

## Стек

SQLAlchemy 2.0 **async** + aiosqlite + Alembic (§4.3, без правок). PyJWT (HS256), bcrypt. FastAPI. Python 3.13/uv/pytest/ruff. Новые зависимости: `sqlalchemy`, `aiosqlite`, `alembic`, `pyjwt`, `bcrypt`.

## Архитектура и файлы (слои §4.9)

Новые модули (auth не трогает игровой домен — независим):
```
app/db/
  engine.py        # async engine + async_sessionmaker; PRAGMA WAL/foreign_keys/busy_timeout
  session.py       # get_session() — async-зависимость FastAPI (commit/rollback)
  base.py          # DeclarativeBase
app/models/user.py # ORM-модель User
app/dal/users.py   # запросы по users (ORM): by_id / by_username / list / create / update / delete / count_admins
app/auth.py        # bcrypt, JWT create/decode, CurrentUser, get_current_user, require_admin,
                   #   bump_token_epoch, sliding-refresh флаги
app/services/auth_service.py   # login (rate-limit + verify), get_me
app/services/admin_service.py  # user CRUD, is_last_admin, bump epoch на смену роли/пароля
app/routers/auth.py            # /api/auth/login · logout · me
app/routers/admin.py           # /api/admin/users CRUD (+ reset-password)
app/dtos/auth.py               # LoginRequest, AuthUserResponse, … (pydantic)
app/exceptions.py              # AuthError/ForbiddenError/ConflictError/BadInputError/RateLimitError/NotFoundError
app/error_handlers.py          # register_error_handlers(app): класс→статус, body {"detail": …}
app/app_factory.py             # create_app(): lifespan(БД), middlewares, роутеры, /api/health
app/middleware/
  security_headers.py # CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS(secure), Permissions-Policy
  csrf.py             # X-Requested-With на /api/ небезопасных методах → 403
  refresh.py          # переставить cookie, если get_current_user пометил refresh
alembic/             # миграции; первая — users
scripts/create_admin.py  # CLI bootstrap первого админа (async, через ORM)
```
`app/config.py` (существует, pydantic-settings) — расширяем auth-настройками. Роутеры тонкие; сервисы оркеструют; DAL — единственный к БД; `app/auth.py` — чистые крипто/JWT + одна async-зависимость.

## БД и сессия

- **Engine:** `create_async_engine("sqlite+aiosqlite:///<path>")`; PRAGMA (`journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout`) вешаются на event `connect` **`engine.sync_engine`** (не на `AsyncEngine` напрямую — иначе событие не подключится; типичная aiosqlite-грабля).
- **Сессия:** `async_sessionmaker`; зависимость `get_session()` — `yield session`; **commit ТОЛЬКО при незакоммиченных изменениях** (`if session.in_transaction(): await session.commit()`), rollback на ошибке, close в finally. Важно: `get_current_user` под `Depends` делает read-only `SELECT token_epoch` на КАЖДОМ защищённом запросе — безусловный `await session.commit()` дал бы лишний fsync на каждый GET (и на открытие SSE-подписки в срезе 2). Read-only пути не коммитят.
- **Lifespan:** на старте — engine (+ опц. проверка соединения); на остановке — `engine.dispose()`. (Срез 2 добавит сюда владение процессом Rapfi.)
- **Миграции:** Alembic с async-engine. `env.py` — `connectable.connect()` + `connection.run_sync(do_run_migrations)` (async-обёртка online-режима). Первая ревизия — таблица `users`. Прогон — `alembic upgrade head` отдельной командой (перед bootstrap).

## Модель User (таблица `users`)

Колонки (§4.3 + порт librarium, минус library-специфика):
```
users:
  id            INTEGER PK
  username      TEXT UNIQUE NOT NULL
  password_hash TEXT NOT NULL          # bcrypt
  role          TEXT NOT NULL DEFAULT 'user'   # 'admin' | 'user'  (renju: user, НЕ reader)
  token_epoch   INTEGER NOT NULL DEFAULT 0     # отзыв сессий, §4.4
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
```
Роли renju — `admin`/`user` (в librarium было `admin`/`reader`). `display_name`/`email` librarium — не тащим (нет нужды в MVP; добавимо позже аддитивно).

## Авторизация (перенос алгоритмов)

DB-независимое — **дословно** из librarium:
- `hash_password`/`verify_password` — bcrypt. (bcrypt молча усекает пароль до 72 байт — DTO создания/reset валидирует разумную длину пароля.)
- `create_token(user_id, role, token_epoch)` — JWT HS256, payload `{userId, role, tep, iat, exp}`, TTL `JWT_EXPIRE_HOURS`.
- `decode_token` — verify подписи; `ExpiredSignatureError`/`InvalidTokenError` → `AuthError`.
- `CurrentUser{user_id, role}` (frozen) + `from_payload` — строгая валидация формы payload (bool-guard на `userId`, role непустая строка), при нарушении — generic `AuthError("Invalid token")`, причина в лог, не в ответ.
- `require_admin` — `role != "admin"` → `ForbiddenError`.
- `token_needs_refresh` — токен старше `JWT_REFRESH_AFTER_HOURS` → пометить refresh. **Грабля переноса:** `iat` кладётся в токен как `datetime`, но PyJWT декодирует его как **unix-timestamp** → сравнение через `datetime.fromtimestamp(iat, tz=utc)`, НЕ как datetime (иначе TypeError / всегда-refresh).
- rate-limit логина (`auth_service`) — module-level окно 5 попыток / 300с по IP (`X-Real-IP`/`X-Forwarded-For`/`client.host`), `RateLimitError` → 429. **Переносим анти-DoS-кэп `_MAX_TRACKED_IPS` (~10k) + purge протухших** — иначе словарь попыток растёт неограниченно (IP клиент-управляем до прокси через `X-Forwarded-For`). Секции чтения/записи словаря **синхронны (без `await`)** → в одном event loop атомарны, отдельный лок НЕ нужен (в librarium был `threading.Lock` из-за sync-FastAPI с threadpool — реальный параллелизм; здесь его нет).

БД-касания — **на ORM (async)**:
- `get_current_user(request, session)`: cookie → `decode_token` → `CurrentUser.from_payload` → **`SELECT token_epoch FROM users WHERE id`** (ORM) → сверить с `tep` → mismatch = `AuthError` (отозвано). Без кеша (см. ниже). Пометить refresh при необходимости.
- `bump_token_epoch(session, user_id) -> int | None`: `UPDATE users SET token_epoch = token_epoch + 1 … RETURNING token_epoch` — **вернуть новый epoch или `None`, если строки нет** (bump несуществующего/удалённого юзера не молчит на 0 строк — guard на гонку reset-password×delete). Зовётся из admin-флоу на смену роли / сброс пароля (мгновенный отзыв со всех устройств, §4.4).
- `login`: `dal.get_user_by_username` → `verify_password` → `create_token(... token_epoch)`.

## `token_epoch` без кеша — обоснование и триггер-возврата

**Почему librarium завёл in-memory кеш epoch** (`dict[user_id→epoch]` + dirty-set + after-commit-хуки + legacy-режим): там **каждая обложка идёт под cookie-auth**, а страница библиотеки = сетка из десятков книг → десятки параллельных authed-запросов на рендер. Per-request `SELECT token_epoch` под этот фан-аут не просто тормозил — **стампед под общий ресурс (SQLite-локи/threadpool) клинил весь процесс**. Кеш был предохранителем от lock-up.

**Почему здесь не нужен:** в renju такого authed-fan-out нет **по определению** — одна партия, ходы человеко-темпом, **один долгоживущий SSE-стрим** (auth раз на подписке, дальше течёт), доска рисуется на клиенте, статика PWA отдаётся мимо `get_current_user`, и мы выбрали **SSE вместо polling** (polling как раз и наплодил бы повторные authed-запросы). Per-request чтение epoch — один index-seek по PK на локальном SQLite (в WAL читатели не блокируют писателя), на низком трафике это шум.

**Что выкидываем (и не теряем):** дроп кеша = дроп самого баг-склонного кода (dirty-set/after-commit-упорядоченность существуют ТОЛЬКО ради когерентности кеша). Отзыв сессий сохраняется **полностью и без окна устаревания** (БД читается каждый раз). Бонус: чтение из БД корректно при любом числе воркеров (in-process кеш не пробрасывает отзыв между процессами). Legacy-режим тоже не нужен — greenfield, `token_epoch` есть с первой миграции.

**Триггер-возврата (записан намеренно):** если у renju появится authed-хот-пас (аватарки в большом списке, превью, или уход в polling) — кеш снова осмыслен; реализация в `librarium-py/backend/app/auth.py` — готовый чертёж.

## Эндпоинты

Префикс `/api` (отделяет API от будущей SPA-статики; §4.6 бареовые пути получают `/api`).

**Auth** (`app/routers/auth.py`):
- `POST /api/auth/login {username, password}` → ставит httpOnly-cookie (`SameSite=Lax`, `Secure` по env, `max_age=TTL`), тело `{ok, user}`, где `user` — тот же DTO, что и `/me` (`{id, username, role}`).
- `POST /api/auth/logout` → удаляет cookie (epoch не трогаем — §4.4).
- `GET /api/auth/me` (под `get_current_user`) → `{id, username, role}`.

**Admin users** (`app/routers/admin.py`, всё под `require_admin`; §4.6):
- `GET /api/admin/users` → список.
- `POST /api/admin/users {username, password, role}` → создать (открытой регистрации нет — создаёт админ, §4.4). → `{id}`.
- `DELETE /api/admin/users/{id}` → удалить. Guard'ы (порт librarium): **нельзя удалить самого себя** (`actor_id == id` → `ConflictError`), **нельзя снести последнего админа** (`is_last_admin` → `ConflictError`). Несуществующий `id` → `NotFoundError` (404).
- `POST /api/admin/users/{id}/reset-password {password}` → сменить хеш + **`bump_token_epoch`** (отзыв сессий). Несуществующий `id` → `NotFoundError` (404). Смена роли (если будет в PUT) — тоже bump.

## Middlewares (порядок важен)

1. **security_headers** — на ответ, набор по §5.3 основной спеки: `Content-Security-Policy`: `default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; connect-src 'self'` (script-src — nonce/hash для inline Vite, без unsafe-inline; connect-src — под SSE); `X-Content-Type-Options: nosniff`; `X-Frame-Options: DENY`; `Referrer-Policy: same-origin`; `Permissions-Policy`; `Strict-Transport-Security` (когда `Secure`/прод). **Это и есть «правильно вместо nginx».**
2. **csrf** — на `/api/` небезопасные методы (не GET/HEAD/OPTIONS) требовать `X-Requested-With: XMLHttpRequest`, иначе 403. Это **header-presence**-проверка (то, что §5.3 называет «double-submit»): браузер не даёт выставить custom-заголовок кросс-сайтово. Под защиту попадает и **сам `login`** (POST `/api/`) — фронт обязан слать заголовок уже на логине, до cookie. SSE — это GET, под защиту не попадает (`EventSource` custom-заголовки слать не может — и не нужно).
3. **refresh** — после хендлера, если `get_current_user` пометил флаг refresh **И присутствуют ВСЕ поля** (`_refresh_user_id`/`_refresh_role`/`_refresh_epoch`) И ответ 2xx/3xx — перевыпустить токен и переставить cookie. Проверять все поля, не только флаг (частичный набор → AttributeError → 500 на валидном запросе).

Плюс generic `Exception`-handler → 500 `{"detail": "Internal server error"}` (без утечки).

## Обработка ошибок (порт `error_handlers.py`)

Класс домен-исключения → статус, body `{"detail": str(exc)}`:
`AuthError→401`, `ForbiddenError→403`, `ConflictError→409`, `BadInputError→400`, `RateLimitError→429`, `NotFoundError→404`. Handler'ы на **custom-типы** (случайный `raise ValueError` уходит в 500, не в 400). `UpstreamError` librarium не тащим (нет upstream в этом срезе).

## Конфигурация и секрет

`app/config.py` (pydantic-settings, `RENJU_*`): `data_dir` (env `RENJU_DATA_DIR`, дефолт `<repo>/data`; **в тестах переопределяется**, чтобы не писать секрет/БД в репо), `db_path` (дефолт `data_dir/db.sqlite`), `secret_key` (env; иначе сгенерировать в `data_dir/.secret_key` c `chmod 600` — только при генерации, не когда пришёл из env), `jwt_algorithm="HS256"`, `jwt_expire_hours=168`, `jwt_refresh_after_hours=84`, `cookie_name="renju_token"`, `secure_cookie` (bool, env), `busy_timeout_ms`. CORS-origins — задел под фронт (срез 2/этап 4).

## Bootstrap первого админа

`scripts/create_admin.py` (порт librarium на ORM/async): `uv run python -m scripts.create_admin <username> <password>` → если username занят — выход с ошибкой; иначе `create_user(role="admin")`, **`await session.commit()` + `await engine.dispose()` перед выходом** (иначе event loop закроется с незакрытым aiosqlite-соединением). **Без дефолтов `admin/admin`** (librarium их допускал) — требуем явные аргументы (self-hosted, не плодим слабый дефолт-пароль). Запускается после `alembic upgrade head`.

## Тестирование (зеркалит test-набор librarium)

- **auth.py** — юниты: `hash/verify_password`, `create/decode_token` (valid/expired/tampered), `CurrentUser.from_payload` (валид/битый payload — bool `userId`, пустая role).
- **get_current_user** — нет cookie→401, валид→`CurrentUser`, протухший→401, **epoch-mismatch (после `bump`)→401** (revocation), refresh-флаг ставится по возрасту.
- **login** — успех/неверный пароль (401)/несуществующий юзер/rate-limit (6-я попытка→429)/сброс счётчика после успеха.
- **admin users** — `require_admin` (user→403), create/list/delete, **`is_last_admin`** (снести последнего→409), **нельзя удалить себя** (→409), delete/reset несуществующего `id`→404, reset-password **бампит epoch** (старый токен→401).
- **middlewares** — security-заголовки присутствуют в ответе; CSRF: POST без `X-Requested-With`→403, с ним→ок; refresh переставляет cookie на старом токене.
- **error mapping** — каждое исключение→свой статус; `raise ValueError`→500.
- **migration/DB** — `alembic upgrade head` создаёт `users`; сессия commit/rollback.
- Инструмент: `httpx.AsyncClient` + тестовая БД (временный файл/`:memory:` через отдельный engine), pytest **последовательно**.
- **Ручной smoke (Alexey, шаг 10):** `create_admin` → `curl login` (cookie) → `GET /me` → создать второго юзера через `/admin/users` → войти им → `/admin/*` под ним 403.

## Карта на bd

- `rj-a4k` — этот срез закрывает его **auth+БД+каркас** часть; игровые эндпоинты остаются за срезом 2.
- Срез 2 (`2026-06-11-http-game-contour-design.md`) — пере-садится на этот фундамент: `current_user` реальный, `GameRepository` сразу на SQLite/ORM (уходит стадирование in-memory→SQLite), `controllers` ссылаются на реальные `user_id`. Спеку среза 2 поправлю при переходе (пометка «после фундамента»).
- `rj-8sc` (статус-машина/очередь) — в срезе 2.

## Что НЕ в этом срезе (scope-забор — не предлагать как findings)

- **Игровой контур:** партии/ходы/undo/очередь хода, фасад `Player`, `advance`, движок Rapfi в lifespan, SSE-эндпоинты/`EventHub` — **срез 2**.
- **Per-user настройки** (`user_settings`: undo-политика) — таблица per-user, но осмысленна только с партиями → срез 2.
- **Admin engine-config / уровни-UI** — позже (§4.7, `rj-tan`).
- **Смена роли пользователя через PUT** (полный профиль-CRUD сверх create/delete/reset-password) — минимально; расширение аддитивно.
- **Frontend/PWA, страница логина** — этап 4 (`rj-8wf`); здесь только API + cookie.
- **Восстановление БД/бэкапы, мультиворкер, Postgres** — вне MVP (§3, один воркер).
- **OAuth/2FA/смена своего пароля юзером** — вне MVP; здесь admin-managed аккаунты (§4.4, открытой регистрации нет).
