# Настройки пользователя (rj-xt2)

**Дата:** 2026-06-17  
**Статус:** утверждена

## Что делаем

Полный вертикальный срез: экран «Настройки» с тремя секциями — откаты, управление партиями, смена пароля. Бэкенд: миграция + роутер `/api/settings` + bulk delete в `/api/games`. Фронт: реализация заглушки `SettingsPage.tsx`.

## Вне области

- Настройки движка/уровней — в AdminPage
- Смена имени пользователя
- Настройки для отдельных партий
- Исправление `adapter.release` при удалении партии (discovered work, отдельный тикет)

---

## Бэкенд

### Модель `UserSettings` (`app/models/user_settings.py`)

Текущая модель имеет `current_limit`, `current_limit_enabled`, `finished_limit`, `finished_limit_enabled`. Заменяем двойной лимит на один и добавляем undo-поля:

```python
class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    games_limit: Mapped[int] = mapped_column(default=50)         # 10..100; default=50 — источник правды
    games_limit_enabled: Mapped[bool] = mapped_column(default=True)
    undo_enabled: Mapped[bool] = mapped_column(default=True)
    undo_limit: Mapped[int | None] = mapped_column(default=None) # None = ∞
    undo_after_game_end: Mapped[bool] = mapped_column(default=True)  # default=True — включён
```

Дефолты `games_limit=50` и `undo_after_game_end=True` — источник правды (прототип отображал другие значения, они не нормативны).

### Миграция (`alembic/versions/`)

Одна миграция. Чейнится от текущего head `5d790f3dfeb5` (engine_config). SQLite не поддерживает `DROP COLUMN` напрямую — старые столбцы удаляются через `op.batch_alter_table` (table-recreate). Добавление новых столбцов и backfill делаем **до** batch-блока, пока старые столбцы ещё доступны.

Порядок операций:

**Шаг 1 — добавить новые столбцы** (вне batch, пока старые ещё есть):
```python
op.add_column("user_settings", sa.Column("games_limit", sa.Integer(), nullable=False, server_default="50"))
op.add_column("user_settings", sa.Column("games_limit_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
op.add_column("user_settings", sa.Column("undo_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
op.add_column("user_settings", sa.Column("undo_limit", sa.Integer(), nullable=True))
op.add_column("user_settings", sa.Column("undo_after_game_end", sa.Boolean(), nullable=False, server_default=sa.text("1")))
```

**Шаг 2 — backfill** (пока оба набора столбцов существуют):
```python
op.execute("UPDATE user_settings SET games_limit = MAX(current_limit, finished_limit)")
```
MAX выбран намеренно: расширяем лимит, не сужаем — существующие партии не вытесняются при миграции.

**Шаг 3 — удалить старые столбцы** (batch-recreate):
```python
with op.batch_alter_table("user_settings") as batch_op:
    batch_op.drop_column("current_limit")
    batch_op.drop_column("current_limit_enabled")
    batch_op.drop_column("finished_limit")
    batch_op.drop_column("finished_limit_enabled")
```

Примечание: `tests/unit/test_migration.py` уже прогоняет `alembic upgrade head` — новая миграция будет автоматически проверена CI на синтаксическую корректность. Но **backfill (`MAX(current_limit, finished_limit)`) CI не проверяет** — нужно добавить тест по образцу `test_backfill_frozen_engine_config`: поднять схему до `5d790f3dfeb5`, вставить строку `user_settings(current_limit=30, finished_limit=70)`, накатить `head`, проверить `games_limit == 70`.

### `SettingsRepository` (`app/game/settings_repository.py`)

Обновить `get_or_default` и `upsert`: заменить поля лимитов на `games_limit`/`games_limit_enabled`, добавить три undo-поля. `InMemorySettingsRepository` — аналогично.

### `RetentionService` (`app/game/retention_service.py`)

`evict_current` и `evict_finished` сейчас используют раздельные `current_limit`/`finished_limit`. После миграции оба метода используют одни и те же `settings.games_limit` / `settings.games_limit_enabled`.

### `GameService.undo` (`app/game/service.py`)

**Текущий баг:** строка 247 использует `UndoPolicy()` — дефолтную политику, игнорируя `settings_repo`. Исправить: загрузить настройки пользователя и построить `UndoPolicy` из них.

```python
async def undo(self, game_id: str, user_id: int) -> Game:
    game = await self._load_owned(game_id, user_id)
    settings = await self._settings_repo.get_or_default(user_id)
    policy = UndoPolicy(
        enabled=settings.undo_enabled,
        limit=settings.undo_limit,
        after_game_end=settings.undo_after_game_end,
    )
    check_undo(policy=policy, status=GameStatus(game.status), undo_count=game.undo_count)
    # ... остальное без изменений
```

### Роутер `routers/settings.py` (новый файл)

```
GET  /api/settings            → SettingsDTO
PUT  /api/settings            → SettingsDTO
PUT  /api/settings/password   → 204
```

Подключить в `app_factory.py` рядом с остальными роутерами.

**SettingsDTO** (ответ GET и PUT):

```python
class SettingsDTO(BaseModel):
    games_limit: int
    games_limit_enabled: bool
    undo_enabled: bool
    undo_limit: int | None
    undo_after_game_end: bool
```

Размещается в `routers/settings.py` (не в отдельном dtos-файле — роутер небольшой).

**GET /api/settings** — `settings_repo.get_or_default(user.user_id)` → DTO. Возвращает 200.

**PUT /api/settings** — возвращает 200 + `SettingsDTO` (не 204), чтобы фронт мог обновить baseline из ответа сервера.

```python
class SettingsBody(BaseModel):
    games_limit: int = Field(ge=10, le=100)
    games_limit_enabled: bool
    undo_enabled: bool
    undo_limit: int | None = Field(default=None, ge=1, le=999)
    undo_after_game_end: bool
```

Принять тело → upsert → вызвать `service.enforce_limits(user.user_id)` → вернуть обновлённый DTO.

Фронт **всегда отправляет** текущие значения `games_limit` и `undo_limit` в теле, даже когда соответствующий enabled-флаг `false` — иначе PUT вернёт 422. Скрытый степпер сохраняет последнее значение в state.

**PUT /api/settings/password**:

```python
class PasswordBody(BaseModel):
    current_password: str = Field(max_length=72)  # bcrypt усекает >72 байт (как LoginRequest)
    new_password: str = Field(min_length=6, max_length=72)
```

Логика:
1. `user = await session.get(User, user.user_id)`
2. `verify_password(body.current_password, user.password_hash)` → если не совпадает → 400 `"Неверный текущий пароль"`
3. `user.password_hash = hash_password(body.new_password)` → `await session.flush()`
4. `new_epoch = await bump_token_epoch(session, user.user_id)` → `await session.commit()`
5. **Критично:** `request.state.refresh = {"user_id": user.user_id, "role": user.role, "epoch": new_epoch}` — обязательно с `new_epoch` из шага 4, а не с прежним (middleware/refresh.py выставит cookie с этим значением; если передать старый epoch — пользователь разлогинится на следующем запросе)
6. Вернуть 204 (middleware добавит `Set-Cookie` — это корректно, 204 не запрещает заголовки)

`verify_password`, `hash_password`, `bump_token_epoch` импортировать из `app.auth`.

### `DELETE /api/games?section=current|finished` (`routers/games.py`)

Добавить эндпоинт. `section` — query-параметр типа `Literal["current", "finished"]` (не `Section` enum напрямую — иначе FastAPI примет `section=favorite` и удалит избранные партии). Внутри конвертировать в `Section` для передачи в сервис.

Логика в новом методе `GameService.bulk_delete(user_id, section)`:

```python
async def bulk_delete(self, user_id: int, section: Section) -> int:
    games = await self._repo.list_by_owner(user_id)
    ids = [g.id for g in games if game_section(g.status, g.favorite) is section]
    for game_id in ids:
        await self._repo.delete(game_id)
    return len(ids)
```

`game_section` принимает `bool`, `g.favorite` уже `Mapped[bool]` — `bool()` обёртка не нужна (согласованность с `games.py:87`).

Примечание: bulk_delete не вызывает `adapter.release` — движки осиротевших партий будут погашены idle-sweep'ом. При удалении всех текущих партий это может оставить несколько живых процессов до следующего sweep-цикла. Это осознанный компромисс — тот же что в `delete_game`; исправление в отдельном тикете.

Роутер → 204.

---

## Фронт

### `settings.api.ts` (новый файл, рядом с `admin.api.ts`)

```typescript
import { apiRequest } from "../api/client";

export interface UserSettings {
  games_limit: number;
  games_limit_enabled: boolean;
  undo_enabled: boolean;
  undo_limit: number | null;  // null = ∞
  undo_after_game_end: boolean;
}

export function getSettings(): Promise<UserSettings>
export function saveSettings(body: UserSettings): Promise<UserSettings>
export function changePassword(current_password: string, new_password: string): Promise<void>
```

### `game/api.ts` (добавить функцию)

`bulkDeleteGames` относится к играм — добавить рядом с `deleteGame` в `frontend/src/game/api.ts`:

```typescript
export function bulkDeleteGames(section: "current" | "finished"): Promise<void>
```

Все функции используют `apiRequest` из `../api/client` — он передаёт `credentials: "include"`, ставит CSRF-заголовок на мутирующих запросах и бросает `ApiError` при не-2xx.

### `SettingsPage.tsx`

Загрузка: `useEffect` → `getSettings()` → локальный state. Пока загружается — показать заглушку/spinner в стиле других страниц.

**Секция «Откаты»**

- Toggle «Отмена ходов» (`undo_enabled`) — при `false` строки лимита и «после конца» скрыты
- Степпер «Лимит откатов» (`undo_limit`): `null` = «∞»; «+» из «∞» → 1; «−» из 1 → `null`; шаг 1, верхний предел 999 (соответствует `Field(le=999)` в `SettingsBody`)
- Toggle «Откат после конца партии» (`undo_after_game_end`)
- Кнопка «Сохранить» — disabled пока нет изменений от загруженного значения; `loading` во время запроса; успех — обновить baseline

**Секция «Управление партиями»**

- Toggle «Ограничить» (`games_limit_enabled`) + степпер «Партий на раздел» (`games_limit`): шаг 10, диапазон 10..100; скрыт при `games_limit_enabled = false`
- Кнопка «Сохранить»: если новый `games_limit` меньше текущего baseline — перед отправкой показать диалог подтверждения («Уменьшение лимита удалит старейшие партии сверх нового предела. Продолжить?»). Если лимит не уменьшился или `games_limit_enabled=false` — сохранять без диалога.
- «Удалить текущие» / «Удалить завершённые» — каждая открывает диалог подтверждения; после подтверждения → `bulkDeleteGames(section)` → 204

**Секция «Сменить пароль»**

- Два поля `type="password"`: «Текущий пароль», «Новый пароль»
- Под полями — статичное предупреждение: «После смены пароля другие устройства и вкладки будут отключены» (цвет `sumiFaint`, мелкий шрифт)
- Кнопка «Обновить пароль» — disabled пока оба поля пусты
- При ошибке 400 — `errMsg` под кнопкой

**Диалоги подтверждения**

Встроены в страницу (не отдельный компонент). Стилистика — **точно паттерн UsersTab**: `overlay` (полупрозрачный `rgba(36,29,22,0.45)`) → `modal` (фон `paper`, `border-radius: r`, `box-shadow`). Кнопки: «Отмена» (`cancelBtn`) / деструктивное действие (`dangerBtn` — `vermillionDeep` фон). Классы переиспользуются из `SettingsPage.module.css` по той же схеме что `UsersTab.module.css`.

Три диалога:
- Удалить текущие: «Удалить все текущие партии? Это действие нельзя отменить.» → `bulkDeleteGames("current")`
- Удалить завершённые: «Удалить все завершённые партии? Это действие нельзя отменить.» → `bulkDeleteGames("finished")`
- Уменьшение лимита: «Уменьшение лимита удалит старейшие партии сверх нового предела. Продолжить?» → `saveSettings(...)`

State: `type ConfirmKind = "delete-current" | "delete-finished" | "save-limit" | null`.

### `SettingsPage.module.css`

Расширить существующий файл (сейчас `.wrap`, `.eyebrow`, `.title`, `.stub`). Добавить:

- `.section` — блок секции с разделителем снизу
- `.setrow` — строка настройки: `display: flex; justify-content: space-between; align-items: center`
- `.label` / `.desc` — название и описание строки (`fontSans`, `sumi` / `sumiFaint`)
- `.toggle` / `.toggle.on` — переключатель, стиль из прототипа
- `.stepper` — контейнер `−` / число / `+`; кнопки в стиле `actionBtn` из `UsersTab`
- `.saveBtn` — кнопка «Сохранить»: `vermillion` фон, `#fff` текст, `border-radius: r`
- `.dangerRowBtn` — кнопка «Удалить все»: ghost с `vermillion` рамкой/текстом (аналог `actionBtnDanger`)
- `.overlay`, `.modal`, `.modalTitle`, `.modalFooter`, `.cancelBtn`, `.dangerBtn` — скопировать паттерн из `UsersTab.module.css`
- `.field`, `.errMsg` — поля пароля и ошибка (тот же паттерн)

Все токены через `@value` из `../styles/tokens.module.css`.

---

## Тесты

**Бэкенд — существующие тесты, требующие обновления (иначе suite красный после шага 1):**

- `tests/unit/test_settings_repository.py` — полностью переписать: все конструкторы `UserSettings(current_limit=..., finished_limit=..., *_enabled=...)` заменить на `UserSettings(games_limit=..., games_limit_enabled=..., undo_enabled=..., undo_limit=..., undo_after_game_end=...)`; константы `DEFAULT_CURRENT_LIMIT`/`DEFAULT_FINISHED_LIMIT` убрать, проверять `games_limit=50`
- `tests/unit/test_retention_service.py` — в `test_enforce_limits_evicts_oldest_current`: заменить `current_limit=1, current_limit_enabled=True, finished_limit=50, finished_limit_enabled=True` → `games_limit=1, games_limit_enabled=True`
- `tests/unit/test_game_service_contour.py` — **пять** функций используют старые поля: строки ~397 (`test_finish_sets_finished_at_and_evicts_over_limit`), ~490 (`test_create_evicts_current_over_limit`), ~559 (`test_favorite_only_finished_and_exempt_from_limit`), ~661 (`test_unfavorite_returns_to_finished_and_rechecks_limit`), ~747 (`test_enforce_limits_trims_both_sections`) — заменить на `games_limit=N, games_limit_enabled=True`

**Бэкенд — новые тесты:**
- `tests/unit/test_settings_repository.py` (после переписки) — добавить тесты undo-полей
- `tests/api/test_settings_router.py` — GET/PUT /settings, PUT /settings/password (верный/неверный пароль, бамп epoch, `Set-Cookie` содержит новый epoch), DELETE /games?section=current/finished, DELETE /games?section=favorite → 422

**Фронт:**
- `SettingsPage.test.tsx` — переписать заглушку: рендер с mock API, изменение полей, кнопки save (enabled/disabled), диалог удаления, диалог при уменьшении лимита, ошибка пароля. Шаги 6 и 7 атомарны — реализация и тесты SettingsPage идут вместе, иначе CI красный.

---

## Порядок реализации

1. Миграция + модель (`user_settings.py`) + репозиторий (`settings_repository.py`) + `RetentionService`
2. **Обновить существующие тесты** (`test_settings_repository.py`, `test_retention_service.py`, `test_game_service_contour.py`) → suite зелёный
3. Исправление `GameService.undo` (загрузка `UndoPolicy` из `settings_repo`)
4. `routers/settings.py` + `bulk_delete` в `GameService` + эндпоинт в `routers/games.py`
5. Новые тесты бэкенда (`tests/api/test_settings_router.py`)
6. `settings.api.ts`
7. `SettingsPage.tsx` + `SettingsPage.module.css` + `SettingsPage.test.tsx` (атомарно)
