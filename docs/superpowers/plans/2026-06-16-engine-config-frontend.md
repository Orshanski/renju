# Engine-config фронт (rj-h1p) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) или superpowers:executing-plans для реализации task-by-task. Шаги — чекбоксы (`- [ ]`).

**Goal:** Каркас админки (вкладки Пользователи/Движок/Состояние) + рабочий экран «Движок»: таблица уровней (сила 0–100, время на ход в секундах), тумблер NNUE, «Сохранить» — поверх эндпоинта `/api/admin/engine-config` (rj-8py).

**Architecture:** React 19 / react-router 7. Новый модуль `src/admin/` (API + гейт по роли + страница-каркас + экран «Движок»). `/admin` — отдельный роут под `ProtectedRoute` → `Shell` → новый `AdminRoute` (гейт `role==="admin"`). Данные — через `apiRequest` (`api/client.ts`), per-domain модуль как `game/api.ts`. Стили — CSS-модули + `@value`-токены, визуал по `prototype/index.html` #screen-admin/#atab-engine.

**Tech Stack:** React 19, react-router-dom 7, TS strict (`tsc --noEmit`, без eslint), Vite, тесты vitest+@testing-library+MSW. Источник дизайна: `docs/superpowers/specs/2026-06-16-engine-config-design.md` §4.

**ЕДИНАЯ ФИЧА:** это фронт-часть ОДНОЙ фичи «настройки движка»; бэк (`rj-8py`) — её же часть. Сборка фронта идёт ПОСЛЕ бэка (странице нужен эндпоинт), но **поставка/приёмка/мерж — одной фичей вместе с бэком**, не отдельно. bd-тикеты (rj-8py/rj-h1p) — внутренняя разбивка, на поставку не влияет.

---

## Контракт эндпоинта (rj-8py B4 + спека §3) — фронт на него опирается

- `GET /api/admin/engine-config` → `{ levels: [{ id, name, strength, timeout_ms }], nnue: boolean }` (admin-гейт; не-admin → 403).
- `PUT /api/admin/engine-config`, тело `{ levels: [{ id, strength, timeout_ms }], nnue: boolean }` → возвращает тот же GET-ответ (обновлённый). Бэк-валидация: `strength` 0..100, `timeout_ms` 200..30000.
- **Единицы:** API — миллисекунды (`timeout_ms`). UI показывает/редактирует **секунды** и конвертирует с↔мс (`сек = ms/1000`, `ms = round(сек*1000)`).

---

## Целевая структура файлов

```
frontend/src/
  admin/
    admin.api.ts          # НОВЫЙ: DTO + getEngineConfig/putEngineConfig
    admin.api.test.ts     # НОВЫЙ
    AdminRoute.tsx        # НОВЫЙ: гейт по роли admin (Outlet), как ProtectedRoute
    AdminRoute.test.tsx   # НОВЫЙ
    AdminPage.tsx         # НОВЫЙ: каркас вкладок (Пользователи/Движок/Состояние)
    AdminPage.module.css  # НОВЫЙ
    AdminPage.test.tsx    # НОВЫЙ
    EngineTab.tsx         # НОВЫЙ: таблица уровней + NNUE + Сохранить
    EngineTab.module.css  # НОВЫЙ
    EngineTab.test.tsx    # НОВЫЙ
  App.tsx                 # MODIFY: lazy AdminPage + роут /admin под ProtectedRoute>Shell>AdminRoute
  components/Shell.tsx        # MODIFY: ссылка «Админ» (только role==="admin")
  components/Shell.module.css # MODIFY: стиль ссылки (или переиспользовать .linkbtn)
```

## Вне области этого плана (СОЗНАТЕЛЬНО, спека §5)

- **Наполнение вкладок «Пользователи» (rj-6vk) и «Состояние»/health (rj-1in)** — здесь только ЗАГЛУШКИ «в будущих релизах».
- Per-user конфиги; добавление/удаление уровней (набор фиксирован, имена/уровни с бэка).

## Конвенции

- TDD: тест → красный → минимальная реализация → зелёный → коммит. Из `frontend/`.
- Тесты: `cd frontend && npm test` (= `vitest run`); один файл — `npm test -- src/admin/<file>`. Типы: `npm run typecheck` (= `tsc --noEmit`). Сборка: `npm run build`. **eslint нет** — tsc strict достаточно.
- CSS-модули + явный импорт `@value`-токенов из `../styles/tokens.module.css` (как существующие `*.module.css`). Визуал — по мокапу.
- API — `apiRequest` из `../api/client` (бросает `ApiError`; CSRF-заголовок на не-GET внутри). Per-domain модуль как `game/api.ts`.
- Страницы/экраны — default export для lazy; данные — `useState`/`useEffect` + состояния loading/error (как `pages/NewGamePage.tsx`).

---

## Slice F1 — admin API + DTO

**Files:**
- Create: `frontend/src/admin/admin.api.ts`, `frontend/src/admin/admin.api.test.ts`

- [ ] **Step 1: Падающий тест API (MSW)**

Создать `frontend/src/admin/admin.api.test.ts`:

```ts
import { it, expect } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { getEngineConfig, putEngineConfig } from "./admin.api";

it("getEngineConfig парсит уровни и nnue", async () => {
  server.use(http.get("/api/admin/engine-config", () => HttpResponse.json({
    levels: [{ id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000 }],
    nnue: true,
  })));
  const cfg = await getEngineConfig();
  expect(cfg.nnue).toBe(true);
  expect(cfg.levels[0]).toEqual({ id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000 });
});

it("putEngineConfig шлёт тело и возвращает обновлённое", async () => {
  let body: unknown = null;
  server.use(http.put("/api/admin/engine-config", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json({ levels: [{ id: "novice", name: "Новичок", strength: 9, timeout_ms: 2000 }], nnue: false });
  }));
  const updated = await putEngineConfig({ levels: [{ id: "novice", strength: 9, timeout_ms: 2000 }], nnue: false });
  expect(body).toEqual({ levels: [{ id: "novice", strength: 9, timeout_ms: 2000 }], nnue: false });
  expect(updated.levels[0].strength).toBe(9);
  expect(updated.nnue).toBe(false);
});
```

- [ ] **Step 2: Запустить — красный**

Run: `cd frontend && npm test -- src/admin/admin.api.test.ts`
Expected: FAIL (модуль не найден).

- [ ] **Step 3: Реализация**

Создать `frontend/src/admin/admin.api.ts`:

```ts
import { apiRequest } from "../api/client";

export type LevelConfigDTO = { id: string; name: string; strength: number; timeout_ms: number };
export type EngineConfigDTO = { levels: LevelConfigDTO[]; nnue: boolean };
export type EngineConfigUpdate = {
  levels: { id: string; strength: number; timeout_ms: number }[];
  nnue: boolean;
};

export function getEngineConfig(): Promise<EngineConfigDTO> {
  return apiRequest<EngineConfigDTO>("GET", "/api/admin/engine-config");
}

export function putEngineConfig(body: EngineConfigUpdate): Promise<EngineConfigDTO> {
  return apiRequest<EngineConfigDTO>("PUT", "/api/admin/engine-config", body);
}
```

- [ ] **Step 4: Зелёный + commit**

Run: `cd frontend && npm test -- src/admin/admin.api.test.ts` → PASS. `npm run typecheck` → чисто.

```bash
git add frontend/src/admin/admin.api.ts frontend/src/admin/admin.api.test.ts
git commit -m "feat(rj-h1p): admin engine-config API-модуль + DTO"
```

---

## Slice F2 — гейт по роли admin + роут + ссылка в Shell

**Files:**
- Create: `frontend/src/admin/AdminRoute.tsx`, `frontend/src/admin/AdminRoute.test.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/components/Shell.tsx` (+ `Shell.module.css` при необходимости)

- [ ] **Step 1: Падающий тест гейта**

Создать `frontend/src/admin/AdminRoute.test.tsx` (образец — `auth/ProtectedRoute.test.tsx`; мок `useAuth` через `AuthContext`-провайдер или прямой мок). Кейсы: `role==="admin"` → рендерит `<Outlet/>` (видно дочерний экран); `role==="user"` → редирект на `/`; `loading` → сплэш.

```tsx
import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AdminRoute } from "./AdminRoute";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockAuth,
}));
let mockAuth: { user: { role: string } | null; loading: boolean };

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route element={<AdminRoute />}>
          <Route path="/admin" element={<div>ADMIN OK</div>} />
        </Route>
        <Route path="/" element={<div>HOME</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

it("admin → пускает", async () => {
  mockAuth = { user: { role: "admin" }, loading: false };
  renderAt();
  expect(await screen.findByText("ADMIN OK")).toBeInTheDocument();
});

it("user → редирект на /", async () => {
  mockAuth = { user: { role: "user" }, loading: false };
  renderAt();
  expect(await screen.findByText("HOME")).toBeInTheDocument();
});
```

- [ ] **Step 2: Запустить — красный**

Run: `cd frontend && npm test -- src/admin/AdminRoute.test.tsx`
Expected: FAIL (модуль не найден).

- [ ] **Step 3: AdminRoute**

Создать `frontend/src/admin/AdminRoute.tsx` (по образцу `auth/ProtectedRoute.tsx`):

```tsx
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

// Гейт админки: пускает только role==="admin". Не-admin → на главную (бэк всё равно
// сторожит эндпоинт 403; это UX-гейт, не безопасность).
export function AdminRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div>Загрузка…</div>;
  if (user?.role !== "admin") return <Navigate to="/" replace />;
  return <Outlet />;
}
```

- [ ] **Step 4: Роут в App.tsx**

В `frontend/src/App.tsx`: добавить `const AdminPage = lazy(() => import("./admin/AdminPage"));` и роут под существующими `ProtectedRoute` → `Shell` (рядом с `/`, `/new`, `/game/:id`):

```tsx
<Route element={<AdminRoute />}>
  <Route path="/admin" element={<AdminPage />} />
</Route>
```

(импортировать `AdminRoute` из `./admin/AdminRoute`.) AdminPage появится в F3 — на этом шаге допустимо создать минимальную заглушку `frontend/src/admin/AdminPage.tsx` (`export default function AdminPage(){return <div>admin</div>;}`), чтобы App компилировался; полноценно — F3.

- [ ] **Step 5: Ссылка «Админ» в Shell (только admin)**

В `frontend/src/components/Shell.tsx`: в шапке (рядом с `userchip`/`linkbtn`) добавить ссылку «Админ», видимую при `user?.role === "admin"`, по клику `navigate("/admin")`. Стиль — переиспользовать `.linkbtn` или добавить класс в `Shell.module.css`.

```tsx
{user?.role === "admin" && (
  <button className={styles.linkbtn} onClick={() => navigate("/admin")}>Админ</button>
)}
```

- [ ] **Step 6: Зелёный + suite + commit**

Run: `cd frontend && npm test -- src/admin/AdminRoute.test.tsx` → PASS; `npm test` (весь фронт) зелёный; `npm run typecheck` чисто; `npm run build` собирается.

```bash
git add frontend/src/admin/AdminRoute.tsx frontend/src/admin/AdminRoute.test.tsx frontend/src/admin/AdminPage.tsx frontend/src/App.tsx frontend/src/components/Shell.tsx frontend/src/components/Shell.module.css
git commit -m "feat(rj-h1p): /admin роут + гейт по роли admin + ссылка в Shell"
```

---

## Slice F3 — каркас админки (вкладки) + заглушки

**Files:**
- Create/replace: `frontend/src/admin/AdminPage.tsx`, `frontend/src/admin/AdminPage.module.css`, `frontend/src/admin/AdminPage.test.tsx`

- [ ] **Step 1: Падающий тест каркаса**

Создать `frontend/src/admin/AdminPage.test.tsx`: вкладки Пользователи/Движок/Состояние; по умолчанию активна «Движок» (рабочая); клик по «Пользователи»/«Состояние» показывает заглушку «в будущих релизах»; клик по «Движок» рендерит экран движка. Чтобы не тащить сеть в тест каркаса — замокать `EngineTab` (`vi.mock("./EngineTab", () => ({ EngineTab: () => <div>ENGINE TAB</div> }))`).

```tsx
import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdminPage from "./AdminPage";

vi.mock("./EngineTab", () => ({ EngineTab: () => <div>ENGINE TAB</div> }));

it("по умолчанию — вкладка Движок", async () => {
  render(<AdminPage />);
  expect(await screen.findByText("ENGINE TAB")).toBeInTheDocument();
});

it("вкладки переключаются, Пользователи/Состояние — заглушки", async () => {
  render(<AdminPage />);
  await userEvent.click(screen.getByRole("button", { name: "Пользователи" }));
  expect(screen.getByText(/в будущих релизах/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Состояние" }));
  expect(screen.getByText(/в будущих релизах/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Движок" }));
  expect(screen.getByText("ENGINE TAB")).toBeInTheDocument();
});
```

- [ ] **Step 2: Запустить — красный**

Run: `cd frontend && npm test -- src/admin/AdminPage.test.tsx`
Expected: FAIL.

- [ ] **Step 3: AdminPage (каркас)**

Заменить заглушку `frontend/src/admin/AdminPage.tsx`:

```tsx
import { useState } from "react";
import { EngineTab } from "./EngineTab";
import styles from "./AdminPage.module.css";

type Tab = "users" | "engine" | "health";

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("engine"); // рабочая вкладка по умолчанию
  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Администрирование</div>
      <h1 className={styles.title}>Управление</h1>
      <div className={styles.tabs}>
        <button className={tab === "users" ? styles.active : ""} onClick={() => setTab("users")}>Пользователи</button>
        <button className={tab === "engine" ? styles.active : ""} onClick={() => setTab("engine")}>Движок</button>
        <button className={tab === "health" ? styles.active : ""} onClick={() => setTab("health")}>Состояние</button>
      </div>
      {tab === "engine" && <EngineTab />}
      {tab === "users" && <p className={styles.stub}>Управление пользователями — в будущих релизах.</p>}
      {tab === "health" && <p className={styles.stub}>Состояние и здоровье движка — в будущих релизах.</p>}
    </div>
  );
}
```

`AdminPage.module.css`: классы `wrap`/`eyebrow`/`title`/`tabs`/`active`/`stub` — перенести визуал мокапа (`.admin-tabs`, `.eyebrow`, `.title`, `.sub`) на токены (`@value sumi, sumiSoft, vermillion, fontSerif from "../styles/tokens.module.css"`). На F3 `EngineTab` должен существовать хотя бы заглушкой — создаётся в F4; для компиляции F3 допустимо временно `export function EngineTab(){return null;}` (полноценно — F4). (Тест F3 мокает EngineTab, поэтому его реализация на F3-тест не влияет.)

- [ ] **Step 4: Зелёный + commit**

Run: `cd frontend && npm test -- src/admin/AdminPage.test.tsx` → PASS; `npm run typecheck` чисто.

```bash
git add frontend/src/admin/AdminPage.tsx frontend/src/admin/AdminPage.module.css frontend/src/admin/AdminPage.test.tsx
git commit -m "feat(rj-h1p): каркас админки — вкладки Пользователи/Движок/Состояние (заглушки)"
```

---

## Slice F4 — экран «Движок» (таблица + NNUE + Сохранить)

**Files:**
- Create: `frontend/src/admin/EngineTab.tsx`, `frontend/src/admin/EngineTab.module.css`, `frontend/src/admin/EngineTab.test.tsx`

- [ ] **Step 1: Падающий тест экрана (MSW)**

Создать `frontend/src/admin/EngineTab.test.tsx`. Кейсы:
1. рендерит уровни, время показано в СЕКУНДАХ (`timeout_ms 1000 → "1"`/«1.0»);
2. правка силы + «Сохранить» → PUT с телом в МИЛЛИСЕКУНДАХ (сек→мс);
3. тумблер NNUE → в PUT уходит новый `nnue`;
4. отказ загрузки → сообщение об ошибке;
5. отказ сохранения → сообщение, остаёмся на экране.

```tsx
import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, http, HttpResponse } from "../test/msw";
import { EngineTab } from "./EngineTab";

const CFG = { levels: [{ id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000 }], nnue: true };

it("показывает уровни, время в секундах; правка+сохранить шлёт мс", async () => {
  let body: any = null;
  server.use(
    http.get("/api/admin/engine-config", () => HttpResponse.json(CFG)),
    http.put("/api/admin/engine-config", async ({ request }) => { body = await request.json(); return HttpResponse.json(CFG); }),
  );
  render(<EngineTab />);
  const strength = await screen.findByLabelText(/Новичок.*сила/i); // или по роли spinbutton + порядок; см. разметку
  await userEvent.clear(strength);
  await userEvent.type(strength, "9");
  await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  expect(body.levels[0]).toEqual({ id: "novice", strength: 9, timeout_ms: 1000 }); // секунды 1.0 → 1000 мс
  expect(body.nnue).toBe(true);
});

it("отказ загрузки → ошибка", async () => {
  server.use(http.get("/api/admin/engine-config", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  render(<EngineTab />);
  expect(await screen.findByText(/не удалось загрузить/i)).toBeInTheDocument();
});
```

(Точную локализацию инпутов под `getByLabelText`/`getByRole("spinbutton")` исполнитель приводит в соответствие с разметкой — главное, инпуты доступны по имени уровня + назначению; добавить `aria-label`.)

- [ ] **Step 2: Запустить — красный**

Run: `cd frontend && npm test -- src/admin/EngineTab.test.tsx`
Expected: FAIL.

- [ ] **Step 3: EngineTab**

Создать `frontend/src/admin/EngineTab.tsx`:
- При монтировании `getEngineConfig()` → состояние `{ levels, nnue }` (loading/error). Время в инпутах — `timeout_ms / 1000` секунд.
- Локальное редактируемое состояние: массив строк `{ id, name, strength, timeoutSec }` + `nnue`. Контролируемые number-инпуты: сила (`min=0 max=100`), время сек (`min=0.2 step=0.5`). Каждому инпуту — `aria-label` вида `"<имя> сила"` / `"<имя> время"` для тестов/доступности.
- «Сохранить» → `putEngineConfig({ levels: rows.map(r => ({ id: r.id, strength: r.strength, timeout_ms: Math.round(r.timeoutSec * 1000) })), nnue })` → по успеху обновить состояние из ответа + флаг «Сохранено»; по ошибке (`ApiError`) — сообщение, остаёмся.
- Тумблер NNUE — кнопка с `aria-pressed`/класс `on` (визуал мокапа `.toggle`).
- Разметка по мокапу #atab-engine: `sub` (пояснение), `tbl` (таблица), `setrow`+`toggle` (NNUE), `btn-primary` («Сохранить») — в CSS-модуль `EngineTab.module.css` на токенах.

Скелет:

```tsx
import { useEffect, useState } from "react";
import { getEngineConfig, putEngineConfig } from "./admin.api";
import { ApiError } from "../api/client";
import styles from "./EngineTab.module.css";

type Row = { id: string; name: string; strength: number; timeoutSec: number };

export function EngineTab() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [nnue, setNnue] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getEngineConfig()
      .then((c) => { if (!alive) return; setRows(c.levels.map((l) => ({ id: l.id, name: l.name, strength: l.strength, timeoutSec: l.timeout_ms / 1000 }))); setNnue(c.nnue); })
      .catch(() => alive && setErr("Не удалось загрузить настройки."));
    return () => { alive = false; };
  }, []);

  async function save() {
    if (!rows || busy) return;
    setBusy(true); setSaved(false); setErr(null);
    try {
      const c = await putEngineConfig({
        levels: rows.map((r) => ({ id: r.id, strength: r.strength, timeout_ms: Math.round(r.timeoutSec * 1000) })),
        nnue,
      });
      setRows(c.levels.map((l) => ({ id: l.id, name: l.name, strength: l.strength, timeoutSec: l.timeout_ms / 1000 })));
      setNnue(c.nnue);
      setSaved(true);
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Не удалось сохранить.");
    } finally {
      setBusy(false);
    }
  }

  if (err && !rows) return <p className={styles.sub}>{err}</p>;
  if (!rows) return <p className={styles.sub}>Загрузка…</p>;

  const setRow = (id: string, patch: Partial<Row>) =>
    setRows((rs) => rs!.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  return (
    <div>
      <p className={styles.sub}>Сила и время раздумий по уровням — калибруется на живой игре. Сила 0–100. Применяется к новым партиям.</p>
      <table className={styles.tbl}>
        <thead><tr><th>Уровень</th><th>Сила (0–100)</th><th>Время на ход, с</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td>
              <td><input type="number" min={0} max={100} aria-label={`${r.name} сила`} value={r.strength}
                onChange={(e) => setRow(r.id, { strength: Number(e.target.value) })} /></td>
              <td><input type="number" min={0.2} step={0.5} aria-label={`${r.name} время`} value={r.timeoutSec}
                onChange={(e) => setRow(r.id, { timeoutSec: Number(e.target.value) })} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className={styles.setrow}>
        <div><div className={styles.label}>Нейросеть (NNUE)</div><div className={styles.desc}>Полная сила движка. Выключить — режим на слабом CPU.</div></div>
        <button type="button" role="switch" aria-checked={nnue} aria-label="Нейросеть"
          className={nnue ? `${styles.toggle} ${styles.on}` : styles.toggle} onClick={() => setNnue((v) => !v)} />
      </div>
      <div className={styles.actions}>
        <button className={styles.save} disabled={busy} onClick={save}>Сохранить</button>
        {saved && <span className={styles.ok}>Сохранено</span>}
        {err && rows && <span className={styles.errMsg}>{err}</span>}
      </div>
    </div>
  );
}
```

(Числа из мокапа — лишь визуальный плейсхолдер; реальные значения приходят из GET. Валидацию границ держит бэк; UI-инпуты дают `min/max/step` как подсказку.)

- [ ] **Step 4: Зелёный + suite + commit**

Run: `cd frontend && npm test -- src/admin/EngineTab.test.tsx` → PASS; `npm test` (весь фронт) зелёный; `npm run typecheck` чисто; `npm run build` собирается.

```bash
git add frontend/src/admin/EngineTab.tsx frontend/src/admin/EngineTab.module.css frontend/src/admin/EngineTab.test.tsx
git commit -m "feat(rj-h1p): экран «Движок» — таблица уровней + NNUE + Сохранить (секунды↔мс)"
```

---

## Финальная проверка (rj-h1p)

- [ ] `cd frontend && npm test` зелёный целиком; `npm run typecheck` 0 ошибок; `npm run build` собирается (dist обновится — его доставляет бэк, см. модель доставки фронта).
- [ ] **Приёмка (Alexey) — кликом по странице против живого движка** (это и есть ручное тестирование ВСЕЙ фичи): зайти Админ → Движок, поправить силу/время уровня, переключить нейросеть, «Сохранить»; создать партию на этом уровне → убедиться, что применилось (новая партия идёт с новыми числами; nnue=off — классика). Затем — ОДИН мерж всей фичи (бэк rj-8py + фронт rj-h1p).

## Self-review

- **Покрытие спеки §4:** каркас админки (вкладки, Users/Состояние — заглушки) F3 ✓; экран «Движок» (таблица сила/время-в-секундах, тумблер NNUE, Сохранить) F4 ✓; время с↔мс на фронте F4 ✓; admin-гейт F2 ✓; API F1 ✓.
- **Контракт с бэком:** GET/PUT `/api/admin/engine-config`, тело PUT `{levels:[{id,strength,timeout_ms}],nnue}`, мс — совпадает с rj-8py B4.
- **Единая фича:** поставка/приёмка/мерж вместе с бэком; bd-разбивка не влияет на поставку.
- **Открытое для исполнителя (детерминировать, не placeholder):** точная локализация инпутов под `getByLabelText`/`getByRole` (добавить `aria-label`); перенос классов мокапа в CSS-модули на токенах; дефолтная вкладка — «Движок» (рабочая).
