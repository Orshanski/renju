# Фронт-срез 1: обёртка + auth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Рабочий вход (логин→кука→каркас) и оболочка приложения на React, отдаваемая бэкендом, поверх готового auth-API этапов 1–3.

**Architecture:** Новый `frontend/` (React 19 + Vite + TS). `api`-клиент (`fetch`+cookie+CSRF+централизованный 401) → `AuthContext` (me/login/logout) → react-router (`/login` публичный, `/` защищённый через `ProtectedRoute`) → `Shell`+`HomePage`-заглушка. Стилизация — CSS Modules (inline запрещён CSP). Бэк отдаёт собранный SPA (`StaticFiles` + SPA-fallback). Тесты: Vitest+RTL+msw на логику/поведение; визуал — глазами.

**Tech Stack:** React 19, react-router-dom 7, Vite 6, TypeScript 5, Vitest 4, @testing-library/react, msw 2, jsdom. CSS Modules. Бэк: FastAPI `StaticFiles`.

**Спека:** `docs/superpowers/specs/2026-06-12-frontend-slice1-auth-shell-design.md`.

**Команды:** фронт — из `frontend/`: `npm run dev` (Vite+прокси), `npm run build`, `npm test` (Vitest), `npm run typecheck` (`tsc --noEmit`), `npm run lint`. Бэк — из `backend/`: `uv run pytest -q`. **Один origin:** dev — Vite-прокси `/api`→бэк; prod — бэк отдаёт статику.

---

## File Structure

**Создаём (`frontend/`):**
- `package.json` — зависимости + скрипты.
- `tsconfig.json` — TS-конфиг (strict); один плоский конфиг (`include: ["src"]`), без `tsc -b`/project-references.
- `vite.config.ts` — React-плагин, dev-прокси `/api`, **CSP-чистая сборка** (`modulePreload.polyfill=false`, `assetsInlineLimit=0`, `outDir`), Vitest-конфиг (jsdom, setup).
- `index.html` — точка входа, БЕЗ inline `<script>`/`<style>`.
- `.gitignore` — `node_modules`, `dist`.
- `src/main.tsx` — монтирование `<App/>`.
- `src/App.tsx` — `BrowserRouter` + `AuthProvider` + роуты.
- `src/types.ts` — `User`.
- `src/api/client.ts` — `request`, `ApiError`, 401-перехват (с исключением логина).
- `src/auth/auth.api.ts` — `apiLogin`/`apiLogout`/`apiMe` поверх client.
- `src/auth/AuthContext.tsx` — `AuthProvider`, `useAuth`.
- `src/auth/ProtectedRoute.tsx` — гейт по auth.
- `src/pages/LoginPage.tsx` + `LoginPage.module.css`.
- `src/pages/HomePage.tsx` + `HomePage.module.css`.
- `src/components/Shell.tsx` + `Shell.module.css`.
- `src/styles/theme.module.css` — CSS-переменные (цвета/отступы/брейкпоинт-док).
- `src/test/setup.ts` — jest-dom + msw-сервер lifecycle.
- `src/test/msw.ts` — msw-сервер + хелперы хендлеров.
- Тесты рядом: `src/api/client.test.ts`, `src/auth/AuthContext.test.tsx`, `src/auth/ProtectedRoute.test.tsx`, `src/pages/LoginPage.test.tsx`, `src/components/Shell.test.tsx`.

**Правим (бэк):**
- `backend/app/config.py` — поле `frontend_dist: Path` (дефолт `REPO_ROOT/frontend/dist`).
- `backend/app/app_factory.py` — смонтировать `StaticFiles`+SPA-fallback ПОСЛЕ роутеров (если каталог есть).
- `backend/tests/api/test_spa_serving.py` (создать) — раздача SPA + `/api/*` мимо роутера → 404 JSON.

**Вне скоупа (не трогать):** игровые экраны/доска (срез 2+), SSE-клиент, PWA, Playwright/visual-regression.

---

## Task 1: Scaffold `frontend/` (Vite + TS + Vitest, CSP-чистая сборка)

**Files:** Create `frontend/{package.json,tsconfig.json,vite.config.ts,index.html,.gitignore,src/main.tsx,src/App.tsx,src/test/setup.ts,src/styles/theme.module.css}`. (Корневой `.gitignore` НЕ трогаем — `node_modules/`/`dist/`/`frontend/dist/` там уже есть.)

- [ ] **Step 1: `frontend/package.json`**
```json
{
  "name": "renju-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit",
    "lint": "eslint ."
  },
  "dependencies": {
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-router-dom": "^7.6.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.9.1",
    "@testing-library/react": "^16.3.2",
    "@testing-library/user-event": "^14.6.1",
    "@types/react": "^19.1.0",
    "@types/react-dom": "^19.1.0",
    "@vitejs/plugin-react": "^4.4.1",
    "@vitest/coverage-v8": "^4.1.5",
    "eslint": "^9.0.0",
    "jsdom": "^26.0.0",
    "msw": "^2.14.2",
    "typescript": "^5.8.3",
    "typescript-eslint": "^8.0.0",
    "vite": "^6.3.5",
    "vitest": "^4.1.2"
  }
}
```
- [ ] **Step 2: `frontend/tsconfig.json`** (strict, один плоский конфиг)

Один tsconfig покрывает `src`; **без** `tsc -b`/project-references (поэтому build — `tsc --noEmit && vite build`, см. Step 1). `vite.config.ts` исполняется самим Vite через esbuild и нашим `tsc` не тайпчекается (типы из `/// <reference types="vitest/config" />`) — отдельный `tsconfig.node.json` не нужен. **`"vite/client"` в `types` обязателен** (как в librarium): он объявляет ambient-модули для side-effect/CSS-импортов (`*.module.css`, `import "./styles/theme.module.css"`) и `import.meta.env`; без него TS/LSP ругается «Cannot find module … side-effect import».
```json
{
  "compilerOptions": {
    "target": "ES2022", "useDefineForClassFields": true, "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext", "skipLibCheck": true, "moduleResolution": "bundler",
    "allowImportingTsExtensions": true, "resolveJsonModule": true, "isolatedModules": true,
    "moduleDetection": "force", "noEmit": true, "jsx": "react-jsx",
    "strict": true, "noUnusedLocals": true, "noUnusedParameters": true, "noFallthroughCasesInSwitch": true,
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```
- [ ] **Step 3: `frontend/vite.config.ts`** (прокси + CSP-чистая сборка + Vitest)
```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Без dev-сервера: фронт доставляет БЭК (StaticFiles отдаёт собранный dist/). Vite здесь — только
  // бандлер (build) и тест-раннер (test). Доступ (вкл. Tailscale) — к бэку, не к Vite.
  build: {
    outDir: "dist",
    modulePreload: { polyfill: false }, // CSP: убрать inline polyfill-скрипт (цель — современный Safari)
    assetsInlineLimit: 0, // CSP: не инлайнить ассеты
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"], css: true },
});
```
- [ ] **Step 4: `frontend/index.html`** (БЕЗ inline)
```html
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Рэндзю</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```
- [ ] **Step 5: `frontend/.gitignore`** → `node_modules\ndist\ncoverage`. (Корневой `.gitignore` НЕ трогаем — `node_modules/`/`dist/`/`frontend/dist/` там уже есть.)
- [ ] **Step 6: `frontend/src/test/setup.ts`** (msw lifecycle — наполним сервер в Task 2; пока заглушка)
```ts
import "@testing-library/jest-dom/vitest";
```
- [ ] **Step 6b: `frontend/src/styles/theme.module.css`** (сквозные токены — спека §«Сквозные конвенции»: «токены — один модуль/CSS-переменные», действуют на все срезы). `:root` CSS-модулями не скоупится → переменные глобальны; файл импортируется один раз в `main.tsx` (side-effect). Модули срезов (LoginPage/Shell/HomePage в Task 5–6) ссылаются на `var(--…)` вместо литералов.
```css
/* Сквозные токены. Импорт-side-effect из main.tsx. :root не скоупится CSS-модулями → глобально.
   Брейкпоинт компакта — 900px; CSS-переменные НЕ работают в @media-условиях, поэтому в каждом
   модуле @media (max-width: 900px) стоит литерал, здесь — справочно. */
:root {
  --color-bg: #fff;
  --color-muted: #888;
  --color-border: #ddd;
  --color-border-input: #ccc;
  --color-border-soft: #eee;
  --color-primary: #2d6cdf;
  --color-on-primary: #fff;
  --color-error: #c0392b;
  --radius: 8px;
  --radius-lg: 12px;
  --gap: 12px;
  --pad: 24px;
}
```
- [ ] **Step 7: `frontend/src/App.tsx`** (минимум — заполнится в Task 4)
```tsx
export default function App() {
  return <div>renju</div>;
}
```
- [ ] **Step 8: `frontend/src/main.tsx`**
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/theme.module.css"; // сквозные токены (side-effect, глобальный :root)

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```
- [ ] **Step 9: Установить и проверить.** `cd frontend && npm install`. Затем `npm run build` — успех; проверить **CSP-чистоту**: `grep -nE "<script>[^<]|<style|onload=|style=" dist/index.html` → НИЧЕГО (только внешний `<script type="module" src=...>` и `<link rel="stylesheet">`). `npm run typecheck` — 0 ошибок. `npm test` — «No test files» (норма, тестов ещё нет).
- [ ] **Step 10: Commit.** `git add frontend && git commit -m "feat(rj-0z2): scaffold frontend (Vite+React+TS+Vitest, CSP-чистая сборка)"`.

---

## Task 2: api-клиент + msw (fetch, cookie, CSRF, 401-перехват)

**Files:** Create `frontend/src/api/client.ts`, `frontend/src/test/msw.ts`; Test `frontend/src/api/client.test.ts`; Modify `frontend/src/test/setup.ts`.

- [ ] **Step 1: msw-сервер `frontend/src/test/msw.ts`**

Дефолтный `GET /api/auth/me`→401 в `setupServer` (переживает `resetHandlers`): `AuthProvider` в `useEffect` БЕЗУСЛОВНО зовёт `apiMe()`, а `onUnhandledRequest:"error"` (setup.ts) уронит любой тест с `AuthProvider` без `me`-хендлера. Дефолт = «не залогинен»; тесты, которым нужен залогиненный, переопределяют через `server.use(...)`.
```ts
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

export const server = setupServer(
  http.get("/api/auth/me", () => HttpResponse.json({ detail: "unauthenticated" }, { status: 401 })),
);
export { http, HttpResponse };
```
- [ ] **Step 2: setup.ts — lifecycle msw.** Заменить `frontend/src/test/setup.ts` на:
```ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./msw";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```
- [ ] **Step 3: Падающий тест `frontend/src/api/client.test.ts`**
```ts
import { describe, it, expect, vi } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { apiRequest, ApiError, setUnauthorizedHandler } from "./client";

describe("apiRequest", () => {
  it("GET парсит JSON, без CSRF-заголовка", async () => {
    let seenXrw: string | null = "init";
    server.use(http.get("/api/ping", ({ request }) => {
      seenXrw = request.headers.get("X-Requested-With");
      return HttpResponse.json({ pong: true });
    }));
    const data = await apiRequest<{ pong: boolean }>("GET", "/api/ping");
    expect(data).toEqual({ pong: true });
    expect(seenXrw).toBeNull(); // GET — безопасный, CSRF-заголовок не нужен
  });

  it("POST шлёт X-Requested-With (CSRF)", async () => {
    let xrw: string | null = null;
    let ct: string | null = null;
    server.use(http.post("/api/thing", ({ request }) => {
      xrw = request.headers.get("X-Requested-With");
      ct = request.headers.get("Content-Type");
      return HttpResponse.json({ ok: true });
    }));
    await apiRequest("POST", "/api/thing", { a: 1 });
    expect(xrw).toBe("XMLHttpRequest");
    expect(ct).toBe("application/json");
    // credentials:"include" НЕ проверяем юнитом: msw/Node не форвардит fetch-init
    // credentials в request.credentials (всегда "same-origin"). Реальную отправку куки
    // покрывает живой смоук (Task 8).
  });

  it("на не-2xx кидает ApiError со status и detail", async () => {
    server.use(http.post("/api/bad", () => HttpResponse.json({ detail: "nope" }, { status: 422 })));
    await expect(apiRequest("POST", "/api/bad")).rejects.toMatchObject({ status: 422, detail: "nope" });
    await expect(apiRequest("POST", "/api/bad")).rejects.toBeInstanceOf(ApiError);
  });

  it("401 дёргает глобальный обработчик; с opts.skipAuthRedirect — НЕ дёргает", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    server.use(http.get("/api/secure", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
    await expect(apiRequest("GET", "/api/secure")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);

    onUnauthorized.mockClear();
    server.use(http.post("/api/login-like", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
    await expect(apiRequest("POST", "/api/login-like", {}, { skipAuthRedirect: true })).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});
```
- [ ] **Step 2b: Прогнать — FAIL.** `cd frontend && npx vitest run src/api/client.test.ts` (модуль не найден).
- [ ] **Step 3: Реализация `frontend/src/api/client.ts`**
```ts
export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}

type Options = { skipAuthRedirect?: boolean };

let unauthorizedHandler: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  unauthorizedHandler = fn;
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export async function apiRequest<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
  opts: Options = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (!SAFE.has(method)) headers["X-Requested-With"] = "XMLHttpRequest"; // CSRF (csrf.py)
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const resp = await fetch(path, {
    method,
    credentials: "include", // httpOnly-кука
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 401 && !opts.skipAuthRedirect) unauthorizedHandler();

  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const j = await resp.json();
      if (j && typeof j.detail === "string") detail = j.detail;
    } catch { /* тело не JSON — оставляем statusText */ }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
```
- [ ] **Step 4: Прогнать — PASS.** `npx vitest run src/api/client.test.ts`.
- [ ] **Step 5: typecheck + commit.** `npm run typecheck`; `git add frontend/src && git commit -m "feat(rj-0z2): api-клиент (fetch+cookie+CSRF+401-перехват) + msw"`.

---

## Task 3: AuthContext (me/login/logout)

**Files:** Create `frontend/src/types.ts`, `frontend/src/auth/auth.api.ts`, `frontend/src/auth/AuthContext.tsx`; Test `frontend/src/auth/AuthContext.test.tsx`.

- [ ] **Step 1: `frontend/src/types.ts`**
```ts
export type User = { id: number; username: string; role: string };
```
- [ ] **Step 2: `frontend/src/auth/auth.api.ts`** (формы login и me РАЗНЫЕ — спека M1)
```ts
import { apiRequest } from "../api/client";
import type { User } from "../types";

// POST /login → { ok, user: User } — user ВЛОЖЕН; логин исключён из глобального 401 (skipAuthRedirect)
export async function apiLogin(username: string, password: string): Promise<User> {
  const resp = await apiRequest<{ ok: boolean; user: User }>(
    "POST", "/api/auth/login", { username, password }, { skipAuthRedirect: true },
  );
  return resp.user;
}

// GET /me → User плоско
export function apiMe(): Promise<User> {
  return apiRequest<User>("GET", "/api/auth/me");
}

export function apiLogout(): Promise<unknown> {
  return apiRequest("POST", "/api/auth/logout");
}
```
- [ ] **Step 3: Падающий тест `frontend/src/auth/AuthContext.test.tsx`**
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, http, HttpResponse } from "../test/msw";
import { AuthProvider, useAuth } from "./AuthContext";

function Probe() {
  const { user, loading, login, logout } = useAuth();
  if (loading) return <div>loading</div>;
  return (
    <div>
      <span>user:{user ? user.username : "none"}</span>
      <button onClick={() => login("alice", "pw")}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

const me = (u: object | null, status = 200) =>
  http.get("/api/auth/me", () => HttpResponse.json(u as object, { status }));

it("на старте me=200 → user установлен", async () => {
  server.use(me({ id: 1, username: "alice", role: "admin" }));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("user:alice")).toBeInTheDocument());
});

it("на старте me=401 → user=none, без ошибки", async () => {
  server.use(me({ detail: "x" }, 401));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("user:none")).toBeInTheDocument());
});

it("на старте me=500 → user=none, без падения (не-401 → console.error)", async () => {
  const spy = vi.spyOn(console, "error").mockImplementation(() => {});
  server.use(me({ detail: "boom" }, 500));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("user:none")).toBeInTheDocument());
  expect(spy).toHaveBeenCalled(); // не-401 логируется, но юзер всё равно null
  spy.mockRestore();
});

it("login разворачивает .user; logout чистит", async () => {
  server.use(
    me({ detail: "x" }, 401),
    http.post("/api/auth/login", () => HttpResponse.json({ ok: true, user: { id: 2, username: "bob", role: "user" } })),
    http.post("/api/auth/logout", () => HttpResponse.json({ ok: true })),
  );
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("user:none")).toBeInTheDocument());
  await userEvent.click(screen.getByText("login"));
  await waitFor(() => expect(screen.getByText("user:bob")).toBeInTheDocument());
  await userEvent.click(screen.getByText("logout"));
  await waitFor(() => expect(screen.getByText("user:none")).toBeInTheDocument());
});
```
- [ ] **Step 3b: Прогнать — FAIL.**
- [ ] **Step 4: Реализация `frontend/src/auth/AuthContext.tsx`**
```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiLogin, apiLogout, apiMe } from "./auth.api";
import { ApiError } from "../api/client";
import type { User } from "../types";

type AuthValue = {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiMe()
      .then(setUser)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401)) {
          console.error("me failed", e); // не 401 — лог, но всё равно «не залогинен»
        }
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(username: string, password: string) {
    setUser(await apiLogin(username, password));
  }
  async function logout() {
    await apiLogout();
    setUser(null);
  }

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
```
- [ ] **Step 5: Прогнать — PASS** (`npx vitest run src/auth/AuthContext.test.tsx`); typecheck; `git commit -m "feat(rj-0z2): AuthContext (me/login/logout, разные формы ответов)"`.

---

## Task 4: ProtectedRoute (гейт по auth)

**Files:** Create `frontend/src/auth/ProtectedRoute.tsx`; Test `frontend/src/auth/ProtectedRoute.test.tsx`.

> `App.tsx` остаётся заглушкой из Task 1 до Task 6 — так каждый коммит компилируется. Полный роутер + провод 401→/login собираются в Task 6, когда уже созданы `LoginPage` (Task 5) и `Shell`/`HomePage` (Task 6). `ProtectedRoute.test.tsx` строит собственное дерево через `MemoryRouter`, App не импортирует.

- [ ] **Step 1: Падающий тест `frontend/src/auth/ProtectedRoute.test.tsx`**
```tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import { AuthProvider } from "./AuthContext";
import { ProtectedRoute } from "./ProtectedRoute";

function tree(initial: string) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/login" element={<div>LOGIN</div>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<div>HOME</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

it("нет user → редирект на /login", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
  tree("/");
  await waitFor(() => expect(screen.getByText("LOGIN")).toBeInTheDocument());
});

it("есть user → рендерит защищённое", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "a", role: "user" })));
  tree("/");
  await waitFor(() => expect(screen.getByText("HOME")).toBeInTheDocument());
});
```
- [ ] **Step 1b: Прогнать — FAIL.**
- [ ] **Step 2: `frontend/src/auth/ProtectedRoute.tsx`**
```tsx
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div>Загрузка…</div>; // сплэш: не моргаем логином при валидной куке
  if (!user) return <Navigate to="/login" replace />;
  return <Outlet />;
}
```
- [ ] **Step 3: Прогнать `ProtectedRoute.test.tsx` — PASS** (`npx vitest run src/auth/ProtectedRoute.test.tsx`); `npm run typecheck` (`App.tsx` — заглушка из Task 1, всё компилируется). Коммит: `git commit -m "feat(rj-0z2): ProtectedRoute (гейт по auth)"`.

---

## Task 5: LoginPage (форма, ошибки 401/429/прочее)

**Files:** Create `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/LoginPage.module.css`; Test `frontend/src/pages/LoginPage.test.tsx`.

- [ ] **Step 1: Падающий тест `frontend/src/pages/LoginPage.test.tsx`**
```tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import { AuthProvider } from "../auth/AuthContext";
import LoginPage from "./LoginPage";

function tree() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>HOME</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}
const me401 = http.get("/api/auth/me", () => HttpResponse.json({ detail: "x" }, { status: 401 }));

it("успешный вход → переход на /", async () => {
  server.use(me401, http.post("/api/auth/login", () =>
    HttpResponse.json({ ok: true, user: { id: 1, username: "alice", role: "user" } })));
  tree();
  await userEvent.type(screen.getByLabelText(/имя/i), "alice");
  await userEvent.type(screen.getByLabelText(/пароль/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /войти/i }));
  await waitFor(() => expect(screen.getByText("HOME")).toBeInTheDocument());
});

it("401 → inline «неверные имя или пароль», пароль очищен, без редиректа", async () => {
  server.use(me401, http.post("/api/auth/login", () => HttpResponse.json({ detail: "Invalid" }, { status: 401 })));
  tree();
  await userEvent.type(screen.getByLabelText(/имя/i), "alice");
  await userEvent.type(screen.getByLabelText(/пароль/i), "bad");
  await userEvent.click(screen.getByRole("button", { name: /войти/i }));
  await waitFor(() => expect(screen.getByText(/неверные имя или пароль/i)).toBeInTheDocument());
  expect(screen.getByLabelText(/пароль/i)).toHaveValue("");
  expect(screen.queryByText("HOME")).not.toBeInTheDocument();
});

it("429 → «слишком много попыток»", async () => {
  server.use(me401, http.post("/api/auth/login", () => HttpResponse.json({ detail: "Too many" }, { status: 429 })));
  tree();
  await userEvent.type(screen.getByLabelText(/имя/i), "alice");
  await userEvent.type(screen.getByLabelText(/пароль/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /войти/i }));
  await waitFor(() => expect(screen.getByText(/слишком много попыток/i)).toBeInTheDocument());
});

it("500/прочее → общий «ошибка входа», без редиректа", async () => {
  server.use(me401, http.post("/api/auth/login", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  tree();
  await userEvent.type(screen.getByLabelText(/имя/i), "alice");
  await userEvent.type(screen.getByLabelText(/пароль/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /войти/i }));
  await waitFor(() => expect(screen.getByText(/ошибка входа/i)).toBeInTheDocument());
  expect(screen.queryByText("HOME")).not.toBeInTheDocument();
});
```
- [ ] **Step 1b: Прогнать — FAIL.**
- [ ] **Step 2: `frontend/src/pages/LoginPage.module.css`**
```css
/* токены — theme.module.css (Task 1 Step 6b) */
.wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; }
.card { width: 100%; max-width: 360px; display: flex; flex-direction: column; gap: var(--gap);
  padding: var(--pad); border: 1px solid var(--color-border); border-radius: var(--radius-lg); }
.field { display: flex; flex-direction: column; gap: 4px; }
.input { padding: 10px 12px; font-size: 16px; border: 1px solid var(--color-border-input); border-radius: var(--radius); }
.button { padding: 10px 12px; font-size: 16px; border: 0; border-radius: var(--radius); cursor: pointer;
  background: var(--color-primary); color: var(--color-on-primary); }
.button:disabled { opacity: 0.6; cursor: default; }
.error { color: var(--color-error); font-size: 14px; }
@media (max-width: 900px) { .card { max-width: 100%; } } /* компакт ≤900 (брейкпоинт-литерал, см. theme.module.css) */
```
- [ ] **Step 3: `frontend/src/pages/LoginPage.tsx`**
```tsx
import { useState, type SyntheticEvent } from "react"; // FormEvent депрекейтнут в @types/react 19
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import styles from "./LoginPage.module.css";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: SyntheticEvent) {
    e.preventDefault();
    if (busy) return; // гард двойного сабмита: Enter повторно, пока идёт запрос
    setBusy(true);
    setError("");
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      setPassword("");
      if (err instanceof ApiError && err.status === 401) setError("Неверные имя или пароль");
      else if (err instanceof ApiError && err.status === 429) setError("Слишком много попыток, повторите позже");
      else setError("Ошибка входа");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <form className={styles.card} onSubmit={onSubmit}>
        <div className={styles.field}>
          <label htmlFor="username">Имя</label>
          <input id="username" className={styles.input} value={username}
            onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </div>
        <div className={styles.field}>
          <label htmlFor="password">Пароль</label>
          <input id="password" type="password" className={styles.input} value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </div>
        {error && <div className={styles.error}>{error}</div>}
        <button className={styles.button} type="submit" disabled={busy}>Войти</button>
      </form>
    </div>
  );
}
```
- [ ] **Step 4: Прогнать — PASS** (`npx vitest run src/pages/LoginPage.test.tsx`); typecheck; `git commit -m "feat(rj-0z2): LoginPage (форма + ошибки 401/429/прочее)"`.

---

## Task 6: Shell + HomePage + App-роутинг (полный флоу)

**Files:** Create `frontend/src/components/Shell.tsx`, `frontend/src/components/Shell.module.css`, `frontend/src/pages/HomePage.tsx`, `frontend/src/pages/HomePage.module.css`; Modify `frontend/src/App.tsx` (полный роутер + провод 401, заменяет заглушку Task 1); Test `frontend/src/components/Shell.test.tsx`.

- [ ] **Step 1: Падающий тест `frontend/src/components/Shell.test.tsx`**
```tsx
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import { AuthProvider } from "../auth/AuthContext";
import { Shell } from "./Shell";

function tree() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/login" element={<div>LOGIN</div>} />
          <Route element={<Shell />}>
            <Route path="/" element={<div>HOME</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

it("показывает имя пользователя и контент", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "alice", role: "user" })));
  tree();
  await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());
  expect(screen.getByText("HOME")).toBeInTheDocument();
});

it("клик «выход» → logout → редирект на /login", async () => {
  server.use(
    http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "alice", role: "user" })),
    http.post("/api/auth/logout", () => HttpResponse.json({ ok: true })),
  );
  tree();
  await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: /выход/i }));
  await waitFor(() => expect(screen.getByText("LOGIN")).toBeInTheDocument());
});
```
- [ ] **Step 1b: Прогнать — FAIL.**
- [ ] **Step 2: `frontend/src/components/Shell.module.css`**
```css
/* токены — theme.module.css (Task 1 Step 6b) */
.shell { min-height: 100vh; display: flex; flex-direction: column; }
.header { display: flex; align-items: center; justify-content: space-between;
  padding: 12px 24px; border-bottom: 1px solid var(--color-border-soft); }
.brand { font-weight: 600; }
.right { display: flex; align-items: center; gap: var(--gap); }
.logout { padding: 6px 12px; border: 1px solid var(--color-border-input); border-radius: var(--radius); cursor: pointer; background: var(--color-bg); }
.main { flex: 1; padding: var(--pad); }
@media (max-width: 900px) { .header { padding: 10px 12px; } .main { padding: 12px; } } /* компакт ≤900 */
```
- [ ] **Step 3: `frontend/src/components/Shell.tsx`**
```tsx
import { Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import styles from "./Shell.module.css";

export function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.brand}>Рэндзю</span>
        <div className={styles.right}>
          <span>{user?.username}</span>
          <button className={styles.logout} onClick={onLogout}>Выход</button>
        </div>
      </header>
      <main className={styles.main}><Outlet /></main>
    </div>
  );
}
```
- [ ] **Step 4: `frontend/src/pages/HomePage.module.css` + `HomePage.tsx`** (заглушка)
```css
/* токены — theme.module.css (Task 1 Step 6b) */
.placeholder { color: var(--color-muted); }
```
```tsx
import styles from "./HomePage.module.css";

export default function HomePage() {
  return <p className={styles.placeholder}>Здесь будет список партий (срез 3).</p>;
}
```
- [ ] **Step 5: `frontend/src/App.tsx`** — заменить заглушку Task 1 на полный роутер + провод 401→/login (все импортируемые модули уже созданы: `AuthProvider` T3, `ProtectedRoute` T4, `LoginPage` T5, `Shell`/`HomePage` T6)
```tsx
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { setUnauthorizedHandler } from "./api/client";
import LoginPage from "./pages/LoginPage";
import HomePage from "./pages/HomePage";
import { Shell } from "./components/Shell";

function UnauthorizedBridge() {
  const navigate = useNavigate();
  useEffect(() => {
    // глобальный 401 (протухшая сессия в любой момент) → на логин. Логин-вызов исключён (skipAuthRedirect).
    setUnauthorizedHandler(() => navigate("/login", { replace: true }));
  }, [navigate]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <UnauthorizedBridge />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<Shell />}>
              <Route path="/" element={<HomePage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
```
- [ ] **Step 6: Прогнать ВЕСЬ фронт — PASS.** `cd frontend && npm test` (все файлы зелёные, App.tsx теперь полный и компилируется); `npm run typecheck`; `npm run build` (CSP-чистая сборка, проверить `dist/index.html` как в Task 1 Step 9).
- [ ] **Step 7: Commit.** `git add frontend/src && git commit -m "feat(rj-0z2): Shell+HomePage + App-роутинг (провод 401), полный фронт-флоу зелёный"`.

---

## Task 7: Бэкенд отдаёт SPA (StaticFiles + SPA-fallback)

**Files:** Modify `backend/app/config.py`, `backend/app/app_factory.py`; Test `backend/tests/api/test_spa_serving.py`.

- [ ] **Step 1: `backend/app/config.py`** — добавить поле рядом с прочими путями:
```python
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"  # RENJU_FRONTEND_DIST
```
- [ ] **Step 2: Падающий тест `backend/tests/api/test_spa_serving.py`** (фикстуры `app`/`client` среза 1; собираем временную «сборку» и направляем `frontend_dist` на неё)
```python
import pytest


@pytest.fixture
async def app_with_spa(tmp_path, monkeypatch):
    monkeypatch.setenv("RENJU_DATA_DIR", str(tmp_path))
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("RENJU_FRONTEND_DIST", str(dist))
    import app.models.game  # noqa: F401
    import app.models.user  # noqa: F401 — обе модели в metadata до create_all (как conftest.app)
    from app.app_factory import create_app
    from app.config import Settings
    from app.db.base import Base

    application = create_app(Settings())
    async with application.router.lifespan_context(application):
        async with application.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield application


@pytest.fixture
async def spa_client(app_with_spa):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=app_with_spa), base_url="http://t") as c:
        yield c


async def test_root_serves_index(spa_client):
    r = await spa_client.get("/")
    assert r.status_code == 200 and "id=root" in r.text


async def test_unknown_client_route_serves_index(spa_client):
    r = await spa_client.get("/login")
    assert r.status_code == 200 and "id=root" in r.text


async def test_asset_served(spa_client):
    r = await spa_client.get("/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text


async def test_unknown_api_is_404_json_not_index(spa_client):
    r = await spa_client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert "id=root" not in r.text  # НЕ SPA-fallback; JSON-ошибка


async def test_health_still_json(spa_client):
    r = await spa_client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"ok": True}


async def test_existing_api_get_wins_over_catchall(spa_client):
    # реальный GET-роут /api/auth/me без куки → 401 JSON, НЕ SPA-fallback:
    # доказывает, что зарегистрированные раньше /api/*-GET-роуты матчатся прежде catch-all.
    r = await spa_client.get("/api/auth/me")
    assert r.status_code == 401
    assert "id=root" not in r.text
```
- [ ] **Step 2b: Прогнать — FAIL.** `cd backend && uv run pytest tests/api/test_spa_serving.py -v`.
- [ ] **Step 3: `backend/app/app_factory.py`** — в КОНЦЕ `create_app`, ПОСЛЕ `include_router(games_router.router)` и `/api/health`, перед `return app`, добавить:
```python
    # SPA: статика + fallback на index.html — ПОСЛЕДними, чтобы не перехватывать /api/*.
    # /api/* мимо роутера отдаёт 404 JSON (см. ниже), не index.html.
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    dist = settings.frontend_dist
    if dist.is_dir():
        dist_root = dist.resolve()
        assets = dist / "assets"
        if assets.is_dir():  # StaticFiles падает, если каталога нет; гард — чтобы частичный dist не ронял старт
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (dist / full_path).resolve()
            # is_relative_to: ../-обход не должен выйти за dist (path-traversal). /assets-mount
            # StaticFiles защищает сам; этот корневой file-branch (favicon и пр.) — нет, гард тут.
            if full_path and candidate.is_file() and candidate.is_relative_to(dist_root):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
```
> Catch-all `GET /{full_path:path}` регистрируется ПОСЛЕ всех `/api/*`-роутеров, поэтому конкретные API-маршруты матчатся раньше. Явная ветка `api/` → 404 JSON закрывает «несуществующий `/api/*` не должен улетать в SPA». `dist.is_dir()`-гард: без собранного фронта (CI/дев-юнит) бэк-тесты не падают, SPA просто не монтируется.
- [ ] **Step 4: Прогнать — PASS.** `uv run pytest tests/api/test_spa_serving.py -v`; затем ВЕСЬ `uv run pytest -q` (StaticFiles не сломал существующее); `uv run ruff check app tests`; из репо-корня `uvx pyright` (0 errors).
- [ ] **Step 5: Commit.** `git add backend && git commit -m "feat(rj-0z2): бэкенд отдаёт SPA (StaticFiles + SPA-fallback, /api/* → 404 JSON)"`.

---

## Task 8: Линт фронта + ручной smoke (живой вход)

**Files:** Create `frontend/eslint.config.js`; ручной smoke.

- [ ] **Step 1: `frontend/eslint.config.js`** (flat-config, TS + React-hooks базово)
```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { languageOptions: { ecmaVersion: 2022, sourceType: "module" } },
);
```
Доустановить dev-deps: `cd frontend && npm i -D @eslint/js`. `npm run lint` — чисто (поправить тривиальные замечания).
- [ ] **Step 2: Полная проверка фронта.** `npm run typecheck` (0), `npm test` (все зелёные), `npm run build` (успех), `grep -nE "<script>[^<]|<style|style=|onload=" dist/index.html` → пусто (CSP-чистота).
- [ ] **Step 3: Ручной smoke (Alexey-делегировано — я сам).** Два терминала:
```bash
# бэк со статикой (--host 0.0.0.0: доступен по Tailscale, не только localhost)
cd backend && RENJU_DATA_DIR=/tmp/renju-fe RENJU_FRONTEND_DIST=$PWD/../frontend/dist uv run uvicorn app.app_factory:create_app --factory --host 0.0.0.0 --port 8000
# (один раз: создать каталог, миграция, админ)
RENJU_DATA_DIR=/tmp/renju-fe uv run alembic upgrade head && RENJU_DATA_DIR=/tmp/renju-fe uv run python -m scripts.create_admin root pw
```
В браузере `http://127.0.0.1:8000/`:
1. Страница рендерится, **консоль без CSP-violation**.
2. Логин `root`/`pw` → каркас с именем `root` и кнопкой «Выход».
3. Refresh — остаёшься залогинен (сессия по куке).
4. «Выход» → редирект на `/login`.
5. Зайти на `/` без куки (инкогнито) → отдаётся страница (200), затем клиентский редирект на `/login`.
6. Неверный пароль → inline «Неверные имя или пароль», поле пароля очищено, без редиректа.
- [ ] **Step 3b: Tailscale-проверка (прод-режим).** С iPad (`ipad1410`) по тайлнету: открыть `http://macbook-pro-orshanski.tail0972f1.ts.net:8000/` (или `http://100.93.96.5:8000/`) → та же страница рендерится, логин работает, **консоль без CSP-violation** (CSP — `'self'`, same-origin, к хосту не привязан; cookie `secure=False` → проходит по http). Подтверждает критерий «iPad-первичный» из спеки вживую.
> Отдельного Vite-dev-сервер-смоука нет: фронт доставляет бэк (Step 3/3b — единственный путь). Vite-dev-сервер из модели убран.
- [ ] **Step 4: Финал.** Полный фронт-прогон + бэк-прогон зелёные. Коммит (если правки линта): `git commit -m "chore(rj-0z2): eslint фронта + smoke-проверка"`.

---

## Self-Review (проведено)

- **Покрытие спеки:** scaffold+CSP-чистая сборка (T1) · api-клиент CSRF/401/login-исключение (T2) · AuthContext me(200/401/500)/login(разворот .user)/logout (T3) · ProtectedRoute-гейт (T4) · LoginPage форма+401/429/500 (T5) · Shell+HomePage+App-роутинг+401-провод+респонсив @900 (T6) · бэк раздаёт SPA+fallback+/api→404 (T7) · линт+ручной smoke с CSP-чек (T8). Все разделы спеки имеют задачу.
- **CSP-чистота:** `modulePreload.polyfill=false`+`assetsInlineLimit=0`+index.html без inline (T1), grep-проверка (T1/T8), смоук-критерий «консоль без violation» (T8). Стили — только CSS Modules (внешний CSS).
- **Формы ответов (M1):** login разворачивает `.user` (T3 `auth.api.ts`), me — плоско; тип `User={id,username,role}` (T3).
- **401-развязка (N1):** глобальный перехват с `skipAuthRedirect`; логин помечен `skipAuthRedirect` (T2 тест + T3 `apiLogin`); 429/прочее → свой текст (T5).
- **Граница API/SPA:** `/api/*` мимо роутера → 404 JSON, не index.html (T7 тест+код).
- **Типы/имена согласованы:** `apiRequest/ApiError/setUnauthorizedHandler` (T2) ← `auth.api` (T3) ← `AuthContext/useAuth` (T3) ← `ProtectedRoute`/`Shell`/`LoginPage` (T4-6). `User` единый (T3).
- **Без плейсхолдеров:** код во всех шагах полный.
- **Ревью-правки (свежий Opus) применены:** B1 build `tsc --noEmit && vite build`, один плоский tsconfig без project-references (T1); B2 убран ненадёжный assertion `request.credentials` — куку проверяет живой смоук (T2/T8); M1 дефолтный `me`→401 в `setupServer` (T2); M2 добавлены ветки `me`=500 (T3) и login=500 (T5); M4 гард каталога `assets` перед mount (T7); M5 GET-якорь порядка роутеров `/api/auth/me`→401 (T7); m5 полный `App.tsx` собирается в T6 (заглушка из T1 до этого) — каждый коммит компилируется.
- **Ре-ревью (2-й свежий Opus), правки применены:** убран осиротевший `tsconfig.node.json` из Files (T1); снята избыточная правка корневого `.gitignore` — уже покрывает `node_modules/`/`dist/`/`frontend/dist/` (T1); реализован `theme.module.css` (токены) + side-effect-импорт в `main.tsx` + модули срезов переведены на `var(--…)` (T1/T5/T6) — закрыт задекларированный-но-не-созданный deliverable спеки §«Сквозные конвенции»; SPA-фикстура импортирует обе модели до `create_all` (T7); catch-all защищён от path-traversal (`is_relative_to(dist_root)`) + убраны мёртвые импорты `_Path`/`Request` (T7). Блокеров/мейджоров во 2-м проходе ревьюер не нашёл.
- **Доставка и Tailscale (поправка Alexey):** фронт доставляет **бэк** (StaticFiles отдаёт собранный `dist/`) — Vite-dev-сервер из модели **убран** (`vite.config` без `server`-блока; Vite = только бандлер+тест-раннер). Доступ, включая Tailscale, — к **бэку**: `uvicorn --host 0.0.0.0` + явная проверка с iPad `http://macbook-pro-orshanski.tail0972f1.ts.net:8000/` (T8 Step 3/3b). CSP `'self'` к хосту не привязан, cookie `secure=False` → http по тайлнету проходит.
- **tsconfig `vite/client` (поправка по LSP, сверено с librarium):** `"types"` включает `vite/client` (T1 Step 2) — ambient-объявления для side-effect/CSS-импортов (`*.module.css`) и `import.meta.env`; без него TS/LSP падал на `import "./styles/theme.module.css"`. (Ошибки LSP вида «Cannot find module react» — отдельное: TS-сервер не пере-сканировал свежий `frontend/node_modules`; `tsc --noEmit`=0 и `vite build` это опровергают.)

## Что НЕ в этом плане (scope — не предлагать как findings)
- Игровая доска, SSE-клиент, ход/undo (срез 2). Список/новая/восстановление (срез 3). Настройки+бэк `/settings` (срез 4). Админка+бэк-эндпоинты (срез 5). «Правила» (срез 6). PWA. Playwright/visual-regression/геометрия-тесты (отложены — тест-дисциплина B).
