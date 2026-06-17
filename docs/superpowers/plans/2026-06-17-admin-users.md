# План: rj-6vk — Админ: экран «Пользователи» + смена роли

## Что делаем

Полный вертикальный срез: бэкенд (PUT /users/{id}, отдельный UserAdminDTO) + фронт (UsersTab).
Бэкенд пользователей уже есть (list/create/delete/reset-password) — добиваем
unified PUT и `created_at` в ответе admin-листинга.
`UserDTO` (auth-контур: `/me`, `/login`) — НЕ трогаем.

## Вне области задачи

Пагинация, поиск, displayName/email, health-вкладка (rj-1in), PWA (rj-puo).
Эндпоинт `/reset-password` остаётся — не удалять, тесты на нём.

---

## Бэкенд

### Задача 1. `UserAdminDTO` в `app/dtos/auth.py`

Добавить рядом с `UserDTO` новый класс (НЕ менять существующий):
```python
class UserAdminDTO(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime
```
`UserDTO` (используется в `auth_service.login` и `auth_service.get_me`) — не трогать.

### Задача 2. Обновить `admin_service.list_users`

`app/services/admin_service.py` — заменить возвращаемый тип и конструктор:
```python
async def list_users(session) -> list[UserAdminDTO]:
    users = await dal.list_users(session)
    return [UserAdminDTO(id=u.id, username=u.username, role=u.role, created_at=u.created_at)
            for u in users]
```

### Задача 3. Обновить роутер `GET /users`

`app/routers/admin.py` — `response_model=list[UserAdminDTO]`, импорт `UserAdminDTO`.

### Задача 4. `PUT /api/admin/users/{id}`

**Тело запроса** `UpdateUserBody`:
```python
class UpdateUserBody(BaseModel):
    role: Literal["admin", "user"] | None = None
    password: str | None = Field(default=None, min_length=1, max_length=72)

    @model_validator(mode="after")
    def at_least_one(self) -> "UpdateUserBody":
        if self.role is None and self.password is None:
            raise ValueError("role или password обязательны")
        return self
    # {}: model_validator → ValueError → pydantic ValidationError → FastAPI 422
    # {password: ""}: min_length=1 → 422 (отдельный путь)
```

**Роутер** — `PUT /api/admin/users/{user_id}`, делегирует `admin_service.update_user`.

**Сервис** `admin_service.update_user(session, target_id, body, actor_id)`:

Порядок проверок (строго):
1. `get_user_by_id(target_id)` → если `None` → `NotFoundError` → 404
2. Если `body.role is not None` И `body.role != target.role` (реальная смена роли):
   a. `actor_id == target_id` → `ConflictError("Нельзя менять свою роль")` → 409
   b. `body.role == "user"` И `is_last_admin(target_id)` → `ConflictError("Нельзя понизить последнего админа")` → 409
   c. `target.role = body.role` + `bump_token_epoch(target_id)`
      (ORM-мутация, как `target.password_hash` в `reset_password`; не добавлять DAL-хелпер)
      Порядок важен: мутация объекта → autoflush при bump → оба изменения в одной транзакции
3. Если `body.role is not None` И `body.role == target.role` — no-op по роли (epoch не бампаем)
4. Если `body.password is not None`: `target.password_hash = hash_password(body.password)` + `bump_token_epoch(target_id)`
   - Смена своего пароля через PUT разрешена: текущая сессия актора умрёт (это нормально —
     фронт показывает кнопку «сброс пароля» на своей строке; после действия → принудительный logout)
5. `await session.commit()`

### Задача 5. Тесты бэкенда (`tests/api/test_admin_users.py`)

Новые кейсы:
- `GET /users` содержит `created_at` в ISO-формате с разделителем `T` (например `"2026-06-17T12:00:00"`):
  SQLite хранит `DATETIME` через `CURRENT_TIMESTAMP` как `YYYY-MM-DD HH:MM:SS` (пробел),
  но SQLAlchemy+aiosqlite парсит в `datetime`, Pydantic сериализует через `.isoformat()` → `T`.
  Тест должен ассертить `assert "T" in user["created_at"]` — без этого фронтовый `split("T")[0]`
  молча отдаст полную строку с пробелом.
- `PUT` меняет роль → `GET /users` показывает новую роль + старый токен цели мёртв (401 `/me`)
- `PUT` нельзя менять свою роль → 409
- `PUT` нельзя понизить последнего админа → 409
- `PUT` несуществующего user_id → 404
- `PUT` меняет пароль → новым паролем логин = 200, старым = 401 (invalid creds)
- `PUT` со своим паролем (актор = цель) → 200, токен актора мёртв
  (тест НЕ перелогинивает актора между PUT и проверкой — иначе маскируется revocation)
- `PUT {}` (пустое тело) → 422
- `PUT {password: ""}` → 422
- `PUT` с той же ролью (no-op) → 200, токен цели жив (epoch не бампался)

---

## Фронт

### Задача 6. `admin.api.ts` — users API

Добавить к существующим engine-функциям:
```ts
export type UserAdminDTO = { id: number; username: string; role: "admin" | "user"; created_at: string }
export type CreateUserBody = { username: string; password: string; role: "admin" | "user" }
export type UpdateUserBody = { role?: "admin" | "user"; password?: string }

export function listUsers(): Promise<UserAdminDTO[]>
export function createUser(body: CreateUserBody): Promise<{ id: number }>
export function updateUser(id: number, body: UpdateUserBody): Promise<{ ok: boolean }>
export function deleteUser(id: number): Promise<{ ok: boolean }>
```
`User` из `types.ts` (`{ id, username, role }`) — не трогать.

### Задача 7. `UsersTab.tsx` + `UsersTab.module.css`

**Таблица** (по прототипу `#atab-users`):
- Колонки: Имя | Роль | Создан | Действия
- Роль: бейдж `<span className={styles.roleBadge} data-role={user.role}>…`
- Дата: `created_at.split("T")[0].split("-").reverse().join(".")` → `DD.MM.YYYY`
  (не `new Date()` — SQLite отдаёт naive-строку без Z, JS трактует как local time → возможен сдвиг даты)
- Действия: «сброс пароля» | «роль» | «удалить»
  - «удалить» скрыт если `user.id === currentUserId`

**Модалка «Создать»** (кнопка «＋ Завести пользователя»):
- username (text), пароль (text), роль (кнопки «Игрок»/«Админ»)
- submit → `createUser()` → ре-фетч списка → закрыть
- ошибка (409 дубликат, 422) → показать `error.detail` под формой (не закрывать)

**Модалка «Сброс пароля»**:
- Поле «новый пароль» (text)
- submit → `updateUser(id, { password })` → закрыть
- ошибка 422 (пустой пароль) → показать под полем
- Если `id === currentUserId` — после успеха вызвать `logout()` из `useAuth()` (актор сам себя разлогинил)

**Модалка «Смена роли»**:
- Кнопки «Игрок» / «Админ», текущая выделена
- submit → `updateUser(id, { role })` → ре-фетч списка → закрыть
- ошибка 409 (своя роль, последний админ) → показать `error.detail` под кнопками

**Confirm удаления**: кастомная модалка (не `window.confirm` — в jsdom требует `vi.spyOn`, в проекте используется кастомный UI).

**Состояния**: loading (скелетон или спиннер), ошибка загрузки (inline).

### Задача 8. `AdminPage.tsx`

Заменить `{tab === "users" && <p …>в будущих релизах</p>}` на `<UsersTab currentUserId={useAuth().user!.id} />`.
`useAuth().user` гарантированно не null — AdminRoute (`user?.role !== "admin"` → Navigate) не пустит без авторизации.

### Задача 9. Тесты фронта

**`admin.api.test.ts`** — добавить тесты для `listUsers`, `createUser`, `updateUser`, `deleteUser`:
паттерн как в engine-тестах: мокаем HTTP, проверяем сериализацию тела запроса и парсинг ответа.

**`AdminPage.test.tsx`** — обновить: мокаем `UsersTab` (`vi.mock('./UsersTab', () => ...)`),
переписать тест «Пользователи/Состояние — заглушки»: теперь только «Состояние» остаётся заглушкой,
«Пользователи» рендерит мок UsersTab.

**`UsersTab.test.tsx`** (новый):
- Рендер списка из мок-данных (имя, роль-бейдж, дата DD.MM.YYYY)
- «удалить» не показывается для строки с `currentUserId`
- Клик «удалить» → модалка подтверждения → подтвердить → `deleteUser` вызван → список ре-фетчнут
- Клик «Завести пользователя» → модалка → submit → `createUser` вызван → список ре-фетчнут
- Клик «Завести пользователя» → ошибка 409 → показан error.detail, модалка не закрылась
- Клик «роль» → модалка → выбор → submit → `updateUser` вызван с `{ role }`
- Клик «роль» → ошибка 409 → показан error.detail
- Клик «сброс пароля» → модалка → submit → `updateUser` вызван с `{ password }`
- Клик «сброс пароля» на себе → после успеха `logout()` вызван

---

## Порядок реализации

1. Бэкенд (задачи 1–5): TDD — сначала тесты, потом код
2. Фронт (задачи 6–9): TDD — сначала тесты, потом компоненты
3. Финальный прогон: `uv run pytest -q` + `uv run ruff check app tests` + `uv run ruff format --check app tests` + `uvx pyright` + `npx vitest run` + `npx tsc --noEmit`
