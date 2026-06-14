# Ретеншн партий — ФРОНТ-срез (rj-as6) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Шаги — чекбоксы (`- [ ]`).

**Goal:** Фронт персонального ретеншна партий: главная = список партий в трёх разделах (Текущие/Завершённые/Избранное), каждый раздел грузится отдельным лёгким запросом с фильтром; контекстные действия по партии (в избранное/из избранного/удалить) по long-tap и правому клику; экран новой партии с выбором уровня (заменяет временную кнопку novice).

**Architecture:** React 19 + react-router-dom 7. Экраны — ленивые chunk'и по роутам (как уже сделано в `App.tsx`). API — поверх `apiRequest` (`src/api/client.ts`). Типы — зеркало бэк-контракта в `src/game/types.ts` (snake_case на проводе). Стили — CSS-модули с `@value`-токенами из `src/styles/tokens.module.css`. Тесты — vitest + @testing-library/react + MSW (`src/test/msw.ts`, `onUnhandledRequest:"error"` — на каждый сетевой вызов нужен handler).

**Tech Stack:** React 19, react-router-dom 7, TypeScript (strict), vitest, @testing-library/react, @testing-library/user-event, MSW.

**Бэкенд готов (этот тикет, бэкенд-срез смержен в ветку).** Доступные эндпоинты:
- `GET /api/games/summary?section=current|finished|favorite` → `GameSummaryDTO[]` (только указанный раздел; невалидный/отсутствующий section → 422).
- `POST /api/games/{id}/favorite` → `true` (тело — голый JSON `true`); на НЕзавершённой партии → 409.
- `POST /api/games/{id}/unfavorite` → `true`.
- `DELETE /api/games/{id}` → 204 (владельцу); чужая/несуществующая → 404.
- `GET /api/levels` → `LevelDTO[]`; `POST /api/games` `{opponent:{kind:"engine",levelId}}` → `GameStateDTO` (уже используются).

`GameSummaryDTO` на проводе (snake_case): `id, status, section, level_id, your_color, move_count, favorite, updated_at, finished_at`.

## Решения по UI (приняты здесь, не оставлены открытыми)
- **Разделы — табы на главной (`/`)**, не отдельные роуты. Текущие — активный по умолчанию (спека §2 «Текущие на главном экране»); Завершённые и Избранное — переключение табом. Каждый таб = один запрос `GET /api/games/summary?section=…` (спека §8 «лёгкий список по разделам»). Глубокие ссылки на раздел не требуются спекой → состояние таба локальное.
- **Экран новой партии — отдельный роут `/new`** (спека §8 «экран новой партии»). На главной кнопка «＋ Новая партия» ведёт на `/new`; там список уровней (`GET /api/levels`) → выбор → `POST /api/games` → переход на `/game/:id`.
- **Контекстные действия — кастомное меню** по `onContextMenu` (правый клик, `preventDefault`) и long-tap **только на тач** (`onPointerDown` заводит таймер 500 мс ТОЛЬКО при `e.pointerType === "touch"`, отменяется при pointerup/pointermove; на unmount — clear). Мышь меню НЕ открывает по long-press — только правым кликом (спека §6 просит long-tap на тач, не на любой pointer). Набор пунктов зависит от раздела карточки: Завершённые → «В избранное», «Удалить»; Избранное → «Из избранного», «Удалить»; Текущие → «Удалить». После действия — перезапрос активного раздела.
- **Отказы действий деградируют молча** (меню остаётся активным, можно повторить — как в существующем HomePage). «В избранное» рендерится только на Завершённой, поэтому 409 (избранное на незавершённой) из UI недостижим — отдельного handler'а не нужно. `section` в запросе summary — всегда валидный enum (тип `Section`), поэтому 422 на плохой section — бэк-контракт (проверяется на бэке), фронт его не достигает.

## Структура файлов
- Modify `frontend/src/game/types.ts` — `Section`, `GameSummaryDTO`.
- Modify `frontend/src/game/api.ts` — `getGamesSummary`, `favoriteGame`, `unfavoriteGame`, `deleteGame`.
- Create `frontend/src/game/api.test.ts` — тесты API-слоя (MSW).
- Create `frontend/src/pages/NewGamePage.tsx` (+ `.module.css`, `.test.tsx`) — экран новой партии.
- Modify `frontend/src/App.tsx` — роут `/new`.
- Modify `frontend/src/pages/HomePage.tsx` (+ `.module.css`, `.test.tsx`) — список из трёх разделов (табы) + кнопка новой партии.
- Create `frontend/src/components/GameCard.tsx` (+ `.module.css`, `.test.tsx`) — карточка партии + контекстное меню действий.
- Create `frontend/src/game/format.ts` (+ `.test.ts`) — чистые хелперы (метка статуса, метка времени раздела).

---

## Task 1: Типы + API-слой

**Files:** Modify `frontend/src/game/types.ts`, `frontend/src/game/api.ts`; Create `frontend/src/game/api.test.ts`.

- [ ] **Step 1: Типы** (`src/game/types.ts`) — добавить:

```ts
export type Section = "current" | "finished" | "favorite";

export type GameSummaryDTO = {
  id: string;
  status: GameStatus;
  section: Section;
  level_id: string | null;
  your_color: Color | null;
  move_count: number;
  favorite: boolean;
  updated_at: string | null; // ISO; null допустим (свежесозданная без БД-значения не приходит в summary)
  finished_at: string | null;
};
```

- [ ] **Step 2: Failing-тесты** (`src/game/api.test.ts`):

```ts
import { it, expect } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { getGamesSummary, favoriteGame, unfavoriteGame, deleteGame } from "./api";

const SUMMARY = [
  { id: "g1", status: "awaiting_move", section: "current", level_id: "novice",
    your_color: "black", move_count: 3, favorite: false, updated_at: "2026-06-13T10:00:00", finished_at: null },
];

it("getGamesSummary дёргает /api/games/summary с section и возвращает массив", async () => {
  let url = "";
  server.use(http.get("/api/games/summary", ({ request }) => {
    url = new URL(request.url).search;
    return HttpResponse.json(SUMMARY);
  }));
  const out = await getGamesSummary("finished");
  expect(url).toBe("?section=finished");
  expect(out).toEqual(SUMMARY);
});

it("favoriteGame POST'ит /favorite и возвращает true", async () => {
  server.use(http.post("/api/games/g1/favorite", () => HttpResponse.json(true)));
  expect(await favoriteGame("g1")).toBe(true);
});

it("unfavoriteGame POST'ит /unfavorite", async () => {
  let hit = false;
  server.use(http.post("/api/games/g1/unfavorite", () => { hit = true; return HttpResponse.json(true); }));
  await unfavoriteGame("g1");
  expect(hit).toBe(true);
});

it("deleteGame DELETE'ит партию и переваривает 204", async () => {
  server.use(http.delete("/api/games/g1", () => new HttpResponse(null, { status: 204 })));
  await expect(deleteGame("g1")).resolves.toBeUndefined();
});
```

- [ ] **Step 3: Прогон — FAIL.** `cd /Users/alexey/code/Renju/frontend && npx vitest run src/game/api.test.ts`

- [ ] **Step 4: Реализация** (`src/game/api.ts`) — добавить (рядом с существующими, тот же стиль):

```ts
import type { GameStateDTO, LevelDTO, GameSummaryDTO, Section } from "./types";

export function getGamesSummary(section: Section): Promise<GameSummaryDTO[]> {
  return apiRequest<GameSummaryDTO[]>("GET", `/api/games/summary?section=${section}`);
}

export function favoriteGame(id: string): Promise<true> {
  return apiRequest<true>("POST", `/api/games/${id}/favorite`);
}

export function unfavoriteGame(id: string): Promise<true> {
  return apiRequest<true>("POST", `/api/games/${id}/unfavorite`);
}

export function deleteGame(id: string): Promise<void> {
  return apiRequest<void>("DELETE", `/api/games/${id}`);
}
```

(Импорт `GameSummaryDTO`/`Section` добавить к существующей `import type { GameStateDTO, LevelDTO }`.)

- [ ] **Step 5: Прогон — PASS** + `npx tsc --noEmit`.

- [ ] **Step 6: Commit** — `cd /Users/alexey/code/Renju && git add frontend/src/game/types.ts frontend/src/game/api.ts frontend/src/game/api.test.ts && git commit -m "feat(rj-as6): фронт — типы summary + API (list-по-разделу/favorite/unfavorite/delete)"`

---

## Task 2: Чистые хелперы отображения

**Files:** Create `frontend/src/game/format.ts`, `frontend/src/game/format.test.ts`.

Карточке нужны человеческие метки; держим их чистыми и тестируемыми отдельно от React.

- [ ] **Step 1: Failing-тесты** (`src/game/format.test.ts`):

```ts
import { it, expect } from "vitest";
import { statusLabel, sectionDateLabel } from "./format";

it("statusLabel: текущая — по твоему ходу; завершённая — по результату", () => {
  expect(statusLabel("awaiting_move", "black")).toBe("Твой ход");
  expect(statusLabel("opponent_thinking", "black")).toBe("Ход соперника");
  expect(statusLabel("finished_black", "black")).toBe("Победа");
  expect(statusLabel("finished_white", "black")).toBe("Поражение");
  expect(statusLabel("finished_draw", "black")).toBe("Ничья");
});

it("sectionDateLabel: текущая — обновлено(updated_at); завершённая/избранная — завершено(finished_at)", () => {
  const s = { updated_at: "2026-06-13T10:00:00", finished_at: "2026-06-12T09:00:00" };
  expect(sectionDateLabel("current", s)).toMatch(/^Обновлено /);
  expect(sectionDateLabel("finished", s)).toMatch(/^Завершено /);
  expect(sectionDateLabel("favorite", s)).toMatch(/^Завершено /);
  expect(sectionDateLabel("current", { updated_at: null, finished_at: null })).toBe("");
});
```

- [ ] **Step 2: Прогон — FAIL.**

- [ ] **Step 3: Реализация** (`src/game/format.ts`):

```ts
import type { Color, GameStatus, Section } from "./types";

export function statusLabel(status: GameStatus, your: Color | null): string {
  if (status === "awaiting_move") return "Твой ход";
  if (status === "opponent_thinking") return "Ход соперника";
  if (status === "finished_draw") return "Ничья";
  const winner: Color = status === "finished_black" ? "black" : "white";
  return your === winner ? "Победа" : "Поражение";
}

function fmt(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function sectionDateLabel(
  section: Section,
  g: { updated_at: string | null; finished_at: string | null },
): string {
  if (section === "current") return g.updated_at ? `Обновлено ${fmt(g.updated_at)}` : "";
  return g.finished_at ? `Завершено ${fmt(g.finished_at)}` : "";
}
```

- [ ] **Step 4: Прогон — PASS** + `npx tsc --noEmit`.

- [ ] **Step 5: Commit** — `cd /Users/alexey/code/Renju && git add frontend/src/game/format.ts frontend/src/game/format.test.ts && git commit -m "feat(rj-as6): фронт — чистые хелперы меток статуса/времени карточки"`

---

## Task 3: Экран новой партии (`/new`)

**Files:** Create `frontend/src/pages/NewGamePage.tsx`, `frontend/src/pages/NewGamePage.module.css`, `frontend/src/pages/NewGamePage.test.tsx`; Modify `frontend/src/App.tsx`.

- [ ] **Step 1: Failing-тест** (`src/pages/NewGamePage.test.tsx`) — по образцу `HomePage.test.tsx`:

```ts
import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import NewGamePage from "./NewGamePage";

it("показывает уровни и по выбору создаёт партию → /game/{id}", async () => {
  let body: unknown = null;
  server.use(
    http.get("/api/levels", () => HttpResponse.json([
      { id: "novice", name: "Новичок" }, { id: "master", name: "Мастер" },
    ])),
    http.post("/api/games", async ({ request }) => { body = await request.json(); return HttpResponse.json({ id: "g7" }); }),
  );
  render(
    <MemoryRouter initialEntries={["/new"]}>
      <Routes>
        <Route path="/new" element={<NewGamePage />} />
        <Route path="/game/:gameId" element={<div>BOARD g7</div>} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole("button", { name: /Мастер/ }));
  expect(await screen.findByText("BOARD g7")).toBeInTheDocument();
  expect(body).toEqual({ opponent: { kind: "engine", levelId: "master" } });
});

it("отказ загрузки уровней → сообщение об ошибке", async () => {
  server.use(http.get("/api/levels", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  render(
    <MemoryRouter initialEntries={["/new"]}>
      <Routes><Route path="/new" element={<NewGamePage />} /></Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText(/Не удалось загрузить уровни/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Прогон — FAIL.**

- [ ] **Step 3: Реализация** (`src/pages/NewGamePage.tsx`):

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getLevels, createGame } from "../game/api";
import type { LevelDTO } from "../game/types";
import styles from "./NewGamePage.module.css";

export default function NewGamePage() {
  const navigate = useNavigate();
  const [levels, setLevels] = useState<LevelDTO[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    getLevels().then((l) => alive && setLevels(l)).catch(() => alive && setErr(true));
    return () => { alive = false; };
  }, []);

  async function pick(levelId: string) {
    if (busy) return;
    setBusy(true);
    try {
      const st = await createGame(levelId);
      navigate(`/game/${st.id}`);
    } catch {
      setBusy(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Новая партия</div>
      <h1 className={styles.title}>Выбери уровень</h1>
      {err && <p className={styles.sub}>Не удалось загрузить уровни.</p>}
      {levels === null && !err && <p className={styles.sub}>Загрузка…</p>}
      <div className={styles.levels}>
        {levels?.map((l) => (
          <button key={l.id} type="button" className={styles.level} disabled={busy} onClick={() => pick(l.id)}>
            {l.name}
          </button>
        ))}
      </div>
    </div>
  );
}
```

`src/pages/NewGamePage.module.css` — по образцу `HomePage.module.css` (те же `@value`-токены `sumiSoft, vermillion, vermillionDeep, shadowSm, fontSerif, fontSans`):

```css
@value sumiSoft, vermillion, vermillionDeep, shadowSm, fontSerif, fontSans from "../styles/tokens.module.css";

.wrap { max-width: 1120px; margin: 0 auto; }
.eyebrow { font-family: fontSerif; font-weight: 600; letter-spacing: 5px; text-transform: uppercase; font-size: 11px; color: vermillion; }
.title { font-family: fontSerif; font-weight: 800; font-size: 40px; line-height: 1.05; margin: 14px 0 18px; letter-spacing: -0.5px; }
.sub { color: sumiSoft; font-size: 15px; font-weight: 300; }
.levels { display: flex; flex-wrap: wrap; gap: 12px; }
.level {
  font-family: fontSans; font-weight: 500; font-size: 15px; cursor: pointer; border: none; border-radius: 11px;
  padding: 14px 22px; background: vermillion; color: #fbeee6; box-shadow: shadowSm; transition: 0.18s;
}
.level:hover:enabled { background: vermillionDeep; transform: translateY(-1px); }
.level:disabled { opacity: 0.6; cursor: default; }
```

- [ ] **Step 4: Роут** (`src/App.tsx`) — добавить ленивый импорт и роут под `Shell`:

```tsx
const NewGamePage = lazy(() => import("./pages/NewGamePage"));
// …внутри <Route element={<Shell />}> рядом с "/" и "/game/:gameId":
<Route path="/new" element={<NewGamePage />} />
```

- [ ] **Step 5: Прогон — PASS** + `npx tsc --noEmit`.

- [ ] **Step 6: Commit** — `cd /Users/alexey/code/Renju && git add frontend/src/pages/NewGamePage.tsx frontend/src/pages/NewGamePage.module.css frontend/src/pages/NewGamePage.test.tsx frontend/src/App.tsx && git commit -m "feat(rj-as6): фронт — экран новой партии (выбор уровня)"`

---

## Task 4: Карточка партии + контекстное меню действий

**Files:** Create `frontend/src/components/GameCard.tsx`, `frontend/src/components/GameCard.module.css`, `frontend/src/components/GameCard.test.tsx`.

Карточка автономна: рендерит summary-партию и сама поднимает меню действий; наружу отдаёт колбэки `onOpen(id)` (переход на партию) и `onChanged()` (родитель перезапрашивает раздел после favorite/unfavorite/delete).

- [ ] **Step 1: Failing-тесты** (`src/components/GameCard.test.tsx`):

```ts
import { it, expect, vi } from "vitest";
import { render, screen, fireEvent, createEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, http, HttpResponse } from "../test/msw";
import { GameCard } from "./GameCard";
import type { GameSummaryDTO } from "../game/types";

const finished: GameSummaryDTO = {
  id: "g1", status: "finished_black", section: "finished", level_id: "master",
  your_color: "black", move_count: 21, favorite: false, updated_at: null, finished_at: "2026-06-12T09:00:00",
};

it("правый клик по завершённой → «В избранное» → POST favorite, зовёт onChanged", async () => {
  const onChanged = vi.fn();
  server.use(http.post("/api/games/g1/favorite", () => HttpResponse.json(true)));
  render(<GameCard game={finished} onOpen={() => {}} onChanged={onChanged} />);
  fireEvent.contextMenu(screen.getByTestId("card-g1"));
  await userEvent.click(await screen.findByRole("menuitem", { name: "В избранное" }));
  await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
});

it("«Удалить» → DELETE, зовёт onChanged", async () => {
  const onChanged = vi.fn();
  server.use(http.delete("/api/games/g1", () => new HttpResponse(null, { status: 204 })));
  render(<GameCard game={finished} onOpen={() => {}} onChanged={onChanged} />);
  fireEvent.contextMenu(screen.getByTestId("card-g1"));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Удалить" }));
  await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
});

it("у текущей в меню только «Удалить» (нет избранного)", async () => {
  const cur: GameSummaryDTO = { ...finished, id: "g2", status: "awaiting_move", section: "current", finished_at: null, updated_at: "2026-06-13T10:00:00" };
  render(<GameCard game={cur} onOpen={() => {}} onChanged={() => {}} />);
  fireEvent.contextMenu(screen.getByTestId("card-g2"));
  expect(await screen.findByRole("menuitem", { name: "Удалить" })).toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "В избранное" })).toBeNull();
});

it("клик по карточке (не по меню) зовёт onOpen", async () => {
  const onOpen = vi.fn();
  render(<GameCard game={finished} onOpen={onOpen} onChanged={() => {}} />);
  await userEvent.click(screen.getByTestId("card-g1"));
  expect(onOpen).toHaveBeenCalledWith("g1");
});

it("long-tap ТОЛЬКО на тач: touch-pointerdown открывает меню, мышь — нет (спека §6)", () => {
  // jsdom без глобального PointerEvent роняет init { pointerType } у fireEvent.pointerDown →
  // строим событие и ставим pointerType явно, иначе хендлер видит undefined.
  const pointerDown = (el: Element, pointerType: string) => {
    const ev = createEvent.pointerDown(el);
    Object.defineProperty(ev, "pointerType", { value: pointerType });
    fireEvent(el, ev);
  };
  vi.useFakeTimers();
  try {
    render(<GameCard game={finished} onOpen={() => {}} onChanged={() => {}} />);
    const card = screen.getByTestId("card-g1");
    pointerDown(card, "mouse"); // мышь — таймер не заводится
    act(() => { vi.advanceTimersByTime(600); }); // setMenu по таймеру → флашим ре-рендер под act
    expect(screen.queryByRole("menu")).toBeNull();
    pointerDown(card, "touch"); // тач — long-tap
    act(() => { vi.advanceTimersByTime(600); });
    expect(screen.getByRole("menu")).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
```

- [ ] **Step 2: Прогон — FAIL.**

- [ ] **Step 3: Реализация** (`src/components/GameCard.tsx`):

```tsx
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { GameSummaryDTO } from "../game/types";
import { favoriteGame, unfavoriteGame, deleteGame } from "../game/api";
import { statusLabel, sectionDateLabel } from "../game/format";
import styles from "./GameCard.module.css";

type Props = { game: GameSummaryDTO; onOpen: (id: string) => void; onChanged: () => void };

const LONG_TAP_MS = 500;

export function GameCard({ game, onOpen, onChanged }: Props) {
  const [menu, setMenu] = useState(false);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  function openMenu(e: { preventDefault: () => void }) {
    e.preventDefault();
    setMenu(true);
  }
  function onPointerDown(e: ReactPointerEvent) {
    if (e.pointerType !== "touch") return; // long-tap — ТОЛЬКО на тач (спека §6); мышь открывает меню правым кликом (onContextMenu)
    timer.current = window.setTimeout(() => setMenu(true), LONG_TAP_MS);
  }
  function cancelLongTap() {
    if (timer.current !== null) { clearTimeout(timer.current); timer.current = null; }
  }
  useEffect(() => cancelLongTap, []); // очистка висячего long-tap-таймера при размонтировании (карточка может уйти после onChanged)

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    try { await action(); setMenu(false); onChanged(); }
    catch { setBusy(false); } // меню остаётся — можно повторить
  }

  return (
    <div
      data-testid={`card-${game.id}`}
      className={styles.card}
      role="button"
      tabIndex={0}
      onClick={() => onOpen(game.id)}
      onContextMenu={openMenu}
      onPointerDown={onPointerDown}
      onPointerUp={cancelLongTap}
      onPointerMove={cancelLongTap}
    >
      <div className={styles.status}>{statusLabel(game.status, game.your_color)}</div>
      <div className={styles.meta}>
        {game.level_id && <span>{game.level_id}</span>}
        <span>ход {game.move_count}</span>
        {game.your_color && <span>ты {game.your_color === "black" ? "чёрные" : "белые"}</span>}
      </div>
      <div className={styles.date}>{sectionDateLabel(game.section, game)}</div>

      {menu && (
        <div className={styles.menu} role="menu" onClick={(e) => e.stopPropagation()}>
          {game.section === "finished" && (
            <button role="menuitem" disabled={busy} onClick={() => run(() => favoriteGame(game.id))}>В избранное</button>
          )}
          {game.section === "favorite" && (
            <button role="menuitem" disabled={busy} onClick={() => run(() => unfavoriteGame(game.id))}>Из избранного</button>
          )}
          <button role="menuitem" disabled={busy} onClick={() => run(() => deleteGame(game.id))}>Удалить</button>
        </div>
      )}
    </div>
  );
}
```

`src/components/GameCard.module.css` — модуль с `@value`-токенами. ОБЯЗАТЕЛЬНЫЕ структурные требования (не пиксели, поведение): `.card { position: relative; }` — якорь для меню; `.menu { position: absolute; }` — всплывает относительно карточки (без `position: relative` на `.card` меню спозиционируется к ближайшему позиционированному предку и уедет). Цвета/отступы — по токенам из `HomePage.module.css`; пункты `[role=menuitem]` читаемые.

- [ ] **Step 4: Прогон — PASS** + `npx tsc --noEmit`.

- [ ] **Step 5: Commit** — `cd /Users/alexey/code/Renju && git add frontend/src/components/GameCard.tsx frontend/src/components/GameCard.module.css frontend/src/components/GameCard.test.tsx && git commit -m "feat(rj-as6): фронт — карточка партии + контекстное меню (избранное/удалить, long-tap/правый клик)"`

---

## Task 5: Главная — три раздела (табы) + вход в новую партию

**Files:** Modify `frontend/src/pages/HomePage.tsx`, `frontend/src/pages/HomePage.module.css`, `frontend/src/pages/HomePage.test.tsx`.

Заменяем заглушку среза 2 (временная кнопка novice) на список: таб-бар разделов + сетка карточек активного раздела + кнопка «＋ Новая партия» → `/new`.

- [ ] **Step 1: Failing-тесты** (`src/pages/HomePage.test.tsx`) — переписать под новый контракт:

```ts
import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import HomePage from "./HomePage";

// HomePage сам EventSource не открывает (только GET /api/games/summary); FakeEventSource не нужен.
function sum(id: string, section: string) {
  return { id, status: section === "current" ? "awaiting_move" : "finished_black", section,
    level_id: "novice", your_color: "black", move_count: 2, favorite: section === "favorite",
    updated_at: "2026-06-13T10:00:00", finished_at: section === "current" ? null : "2026-06-12T09:00:00" };
}

it("грузит Текущие по умолчанию; таб «Завершённые» перезапрашивает свой раздел", async () => {
  server.use(http.get("/api/games/summary", ({ request }) => {
    const s = new URL(request.url).searchParams.get("section");
    return HttpResponse.json(s === "current" ? [sum("c1", "current")] : [sum("f1", "finished")]);
  }));
  render(<MemoryRouter><Routes><Route path="*" element={<HomePage />} /></Routes></MemoryRouter>);
  expect(await screen.findByTestId("card-c1")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: /Завершённые/ }));
  expect(await screen.findByTestId("card-f1")).toBeInTheDocument();
});

it("кнопка «Новая партия» ведёт на /new", async () => {
  server.use(http.get("/api/games/summary", () => HttpResponse.json([])));
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/new" element={<div>NEW SCREEN</div>} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole("button", { name: /Новая партия/ }));
  expect(await screen.findByText("NEW SCREEN")).toBeInTheDocument();
});

it("пустой раздел показывает заглушку", async () => {
  server.use(http.get("/api/games/summary", () => HttpResponse.json([])));
  render(<MemoryRouter><Routes><Route path="*" element={<HomePage />} /></Routes></MemoryRouter>);
  expect(await screen.findByText(/Здесь пусто/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Прогон — FAIL.**

- [ ] **Step 3: Реализация** (`src/pages/HomePage.tsx`):

```tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getGamesSummary } from "../game/api";
import type { GameSummaryDTO, Section } from "../game/types";
import { GameCard } from "../components/GameCard";
import styles from "./HomePage.module.css";

const TABS: { section: Section; label: string }[] = [
  { section: "current", label: "Текущие" },
  { section: "finished", label: "Завершённые" },
  { section: "favorite", label: "Избранное" },
];

export default function HomePage() {
  const navigate = useNavigate();
  const [section, setSection] = useState<Section>("current");
  const [games, setGames] = useState<GameSummaryDTO[] | null>(null);
  const [reloadKey, setReloadKey] = useState(0); // bump → перезапрос текущего раздела после действия (favorite/delete)

  useEffect(() => {
    let alive = true; // guard от гонки: ответ устаревшего раздела не перетирает свежий при быстром переключении табов
    setGames(null);
    getGamesSummary(section).then((g) => alive && setGames(g)).catch(() => alive && setGames([]));
    return () => { alive = false; };
  }, [section, reloadKey]);

  return (
    <div className={styles.wrap}>
      <div className={styles.head}>
        <div className={styles.eyebrow}>Твои партии</div>
        <button type="button" className={styles.newBtn} onClick={() => navigate("/new")}>＋ Новая партия</button>
      </div>
      <div className={styles.tabs} role="tablist">
        {TABS.map((t) => (
          <button key={t.section} role="tab" aria-selected={section === t.section}
            className={section === t.section ? styles.tabActive : styles.tab}
            onClick={() => setSection(t.section)}>{t.label}</button>
        ))}
      </div>
      {games === null && <p className={styles.sub}>Загрузка…</p>}
      {games !== null && games.length === 0 && <p className={styles.sub}>Здесь пусто.</p>}
      <div className={styles.grid}>
        {games?.map((g) => (
          <GameCard key={g.id} game={g} onOpen={(id) => navigate(`/game/${id}`)} onChanged={() => setReloadKey((k) => k + 1)} />
        ))}
      </div>
    </div>
  );
}
```

`HomePage.module.css` — расширить существующий: оставить `@value`-импорт и `.newBtn`; добавить `.head` (flex space-between), `.tabs`/`.tab`/`.tabActive` (таб-бар), `.grid` (сетка карточек). Старые `.title`/`.eyebrow`/`.sub` переиспользовать/подчистить под новый разметку.

- [ ] **Step 4: Прогон — PASS** + весь фронт `npx vitest run` + `npx tsc --noEmit`.

- [ ] **Step 5: Commit** — `cd /Users/alexey/code/Renju && git add frontend/src/pages/HomePage.tsx frontend/src/pages/HomePage.module.css frontend/src/pages/HomePage.test.tsx && git commit -m "feat(rj-as6): фронт — главная: три раздела (табы) + вход в новую партию"`

---

## Ручное тестирование (Alexey, после Task 1–5)

Собрать фронт (`npm run build` → `dist/`, отдаётся бэком). Проверить на живом сервере: главная грузит Текущие; табы Завершённые/Избранное перезапрашивают свой раздел; правый клик / long-tap по карточке даёт меню; «В избранное» (на завершённой) → карточка уходит из Завершённых в Избранное; «Из избранного» → обратно; «Удалить» → исчезает; «＋ Новая партия» → выбор уровня → создаётся партия и открывается доска.

## Самопроверка плана

- **Покрытие спеки:** §2 три раздела (Task 5 табы + Task 1 summary-API по разделу); §5 избранное только из Завершённых / из избранного обратно (Task 4 меню по `section`); §6 действия long-tap/правый клик + удалить (Task 4); §8 лёгкий список по разделам (Task 1 `getGamesSummary`), экран новой партии (Task 3), навигация список↔партия (Task 4 `onOpen`/Task 5 `navigate`, бренд→главная уже был). Лимиты/морда настроек — rj-dix, не здесь.
- **Вне scope (буквально, для ревью плана):** морда настроек лимитов + undo-политика (rj-dix); админка (rj-h1p); авто-удаление по возрасту (отдельный тикет); пагинация (спека §8 — сознательно нет); реконнект/реплей по курсору и выход на список (сделаны в срезе 2). Бэкенд готов (смержен в ветку) — фронт его только потребляет.
- **Типы согласованы:** `GameSummaryDTO`/`Section` (Task 1) ↔ карточка/хелперы (Task 2/4) ↔ главная (Task 5). Контракт зеркалит бэк (snake_case на проводе).
- **Решения приняты, не отложены:** разделы = табы на `/`; новая партия = роут `/new`; меню = onContextMenu + long-tap-таймер; после действия — перезапрос активного раздела (см. «Решения по UI»).
