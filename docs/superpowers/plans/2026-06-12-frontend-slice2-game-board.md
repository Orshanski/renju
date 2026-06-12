# Фронт-срез 2: игровая доска (rj-p82) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Экран игры против движка: DOM-доска 15×15 по прототипу, оптимистичный ход, SSE-живость с reconnect, undo, дебютные зоны, фолы, подсветка выигрышной линии (координаты считает бэк).

**Architecture:** Спека — `docs/superpowers/specs/2026-06-12-frontend-slice2-game-board-design.md` (читать ПЕРЕД работой; контракт SSE и доктрина «отказ = рассинхрон» — там). Бэк: чистая доменная `winning_line` + поле в `_state` + payload финального `status`. Фронт: чистые `reducer`/`legality` (ядро тестов) → хук `useGame` (I/O: GET + EventSource + оптимистика) → презентационный `Board` → `GamePage`.

**Tech Stack:** Бэк: FastAPI, pytest (**последовательно, не параллельно**). Фронт: React 19, TS strict, Vitest+RTL+msw, CSS-модули с `@value`-токенами. Vite — только сборка/тесты, без dev-сервера.

**Конвенции (обязательны):**
- Бэк: пакет `app/**` — ТОЛЬКО относительные импорты (`.x`/`..x`); `tests/**` — абсолютные `app.*`. Домен (`app/domain/`) — без I/O.
- Фронт: дизайн-значения — в CSS-модулях (`@value` из `src/styles/tokens.module.css`); инлайн `style={{}}` — ТОЛЬКО для значений, вычисленных из данных (координаты камней). Новые тулзы не ставить.
- Команды бэка — из `backend/`: `uv run pytest -q`, `uv run ruff check app tests scripts`. Фронта — из `frontend/`: `npx vitest run`, `npx tsc --noEmit`, `npm run build`.
- Коммиты после каждой задачи; ветка `feat/rj-p82-game-board` (уже создана, мы на ней).

---

### Task 1: Бэк — доменная `winning_line`

**Files:**
- Modify: `backend/app/domain/rules.py`
- Test: `backend/tests/unit/test_rules.py` (дописать)

- [ ] **Step 1: Failing-тесты**

В конец `backend/tests/unit/test_rules.py` (там уже есть хелпер `interleave` — использовать его; импорт в шапке файла дополнить):

```python
# шапка файла: from app.domain.rules import outcome_after, winning_line


def test_winning_line_black_horizontal():
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]
    whites = [(0, 0), (2, 0), (4, 0), (6, 0)]
    line = winning_line(interleave(blacks, whites))
    assert line == [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]  # вдоль направления, по возрастанию


def test_winning_line_black_diagonal():
    blacks = [(3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]
    whites = [(0, 5), (0, 7), (0, 9), (0, 11)]
    assert winning_line(interleave(blacks, whites)) == [(3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]


def test_winning_line_white_overline_last_move_mid_series():
    # последний белый ход (7,5) — В СЕРЕДИНЕ серии: лучи в обе стороны, вся шестёрка
    blacks = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0)]
    whites = [(7, 2), (7, 3), (7, 4), (7, 6), (7, 7), (7, 5)]
    line = winning_line(interleave(blacks, whites))
    assert line == [(7, 2), (7, 3), (7, 4), (7, 5), (7, 6), (7, 7)]  # оверлайн целиком


def test_winning_line_none_when_game_ongoing():
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7)]  # четвёрка — не победа
    whites = [(0, 0), (2, 0), (4, 0)]
    assert winning_line(interleave(blacks, whites)) is None


def test_winning_line_none_for_black_overline():
    blacks = [(2, 7), (3, 7), (4, 7), (6, 7), (7, 7), (5, 7)]  # шестёрка чёрных — не победа
    whites = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0)]
    assert winning_line(interleave(blacks, whites)) is None


def test_winning_line_none_on_draw():
    blacks = [(x, y) for y in range(BOARD_SIZE) for x in range(BOARD_SIZE) if (x + 2 * y) % 4 < 2]
    whites = [(x, y) for y in range(BOARD_SIZE) for x in range(BOARD_SIZE) if (x + 2 * y) % 4 >= 2]
    assert winning_line(interleave(blacks, whites)) is None  # ничья — линии нет


def test_winning_line_double_closure_returns_first_direction():
    # (7,7) замыкает И горизонталь, И вертикаль; _DIRECTIONS начинает с (1,0) → горизонталь
    blacks = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 3), (7, 4), (7, 5), (7, 6), (7, 7)]
    whites = [(0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (10, 0), (12, 0), (14, 0)]
    line = winning_line(interleave(blacks, whites))
    assert line == [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]


def test_winning_line_empty_moves():
    assert winning_line([]) is None
```

- [ ] **Step 2: Убедиться, что падают**

Run (из `backend/`): `uv run pytest tests/unit/test_rules.py -q`
Expected: ImportError `cannot import name 'winning_line'`.

- [ ] **Step 3: Реализация**

В `backend/app/domain/rules.py` — `_ray` переписать через новый `_ray_points` (DRY), добавить `winning_line`:

```python
def winning_line(moves: Sequence[Point]) -> list[Point] | None:
    """Точки выигрышной серии последнего хода (вдоль направления, по порядку), или None.

    Те же правила, что outcome_after: чёрные — ровно 5, белые — 5 и длиннее
    (оверлайн возвращается целиком). Партия идёт / ничья → None.
    Один ход замкнул две линии → первая по порядку _DIRECTIONS (для подсветки
    достаточно одной, выбор детерминирован)."""
    if not moves:
        return None
    last = moves[-1]
    mover = color_of_move(len(moves) - 1)
    own = {moves[i] for i in range(len(moves)) if color_of_move(i) is mover}
    for dx, dy in _DIRECTIONS:
        back = _ray_points(own, last, -dx, -dy)
        fwd = _ray_points(own, last, dx, dy)
        run = 1 + len(back) + len(fwd)
        if (mover is Color.BLACK and run == 5) or (mover is Color.WHITE and run >= 5):
            return list(reversed(back)) + [last] + fwd
    return None


def _ray_points(own: set[Point], start: Point, dx: int, dy: int) -> list[Point]:
    """Свои камни подряд от start в направлении (dx, dy), не считая start."""
    pts: list[Point] = []
    x, y = start[0] + dx, start[1] + dy
    while (x, y) in own:
        pts.append((x, y))
        x, y = x + dx, y + dy
    return pts


def _ray(own: set[Point], start: Point, dx: int, dy: int) -> int:
    """Сколько своих камней подряд от start в направлении (dx, dy), не считая start."""
    return len(_ray_points(own, start, dx, dy))
```

- [ ] **Step 4: Зелёные**

Run: `uv run pytest tests/unit/test_rules.py -q` → PASS (все, включая старые).
Run: `uv run ruff check app tests scripts && uv run ruff format app tests scripts` → чисто.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/rules.py backend/tests/unit/test_rules.py
git commit -m "feat(rj-p82): домен winning_line — точки выигрышной серии по последнему ходу"
```

---

### Task 2: Бэк — `winning_line` в state и в финальном `status`-событии

**Files:**
- Modify: `backend/app/routers/games.py` (`_state`)
- Modify: `backend/app/game/service.py` (payload финального `status` в `advance` и `submit_move`)
- Test: `backend/tests/api/test_games_winning_line.py` (новый)

- [ ] **Step 1: Failing-тест**

Создать `backend/tests/api/test_games_winning_line.py`. Фикстуры `app`/`client`/`games_api` — из `tests/conftest.py` (FakeAdapter ходит в первую свободную клетку зоны; цвет человека рандомен → форсируем чёрного monkeypatch'ем):

```python
def _force_black(monkeypatch):
    # патчится атрибут САМОГО модуля random (games.py делает import random) — глобально
    # на время теста; pytest последователен и monkeypatch откатит — безопасно (ревью плана, M2)
    import app.routers.games as games_router

    monkeypatch.setattr(games_router.random, "choice", lambda seq: "black")


async def _play_black_five(client, games_api, gid):
    """Человек-чёрный строит горизонталь y=7 (центр (7,7) предзаполнен).
    (8,7) попадает в дебютную зону 5×5 хода №2; FakeAdapter-белый ходит
    (6,6) (первая клетка зоны 3×3), дальше (0,0),(0,1),(0,2) — не мешает."""
    for x in (8, 9, 10, 11):
        st = await games_api.wait_settled(client, gid)
        assert st["status"] == "awaiting_move"
        r = await client.post(f"/api/games/{gid}/move", json={"x": x, "y": 7})
        assert r.status_code == 202


async def test_state_and_status_event_carry_winning_line(app, client, games_api, monkeypatch):
    _force_black(monkeypatch)
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    ).json()["id"]
    await _play_black_five(client, games_api, gid)

    st = await games_api.wait_settled(client, gid)
    assert st["status"] == "finished_black"
    assert sorted(map(tuple, st["winning_line"])) == [(7, 7), (8, 7), (9, 7), (10, 7), (11, 7)]

    # финальное status-событие несёт ту же линию (контракт SSE; буфер хаба детерминирован)
    status_events = [e for e in app.state.event_hub._log[gid] if e["type"] == "status"]
    assert status_events[-1]["payload"]["status"] == "finished_black"
    assert status_events[-1]["payload"]["winning_line"] == st["winning_line"]
    # нефинальные status поле не несут
    assert all("winning_line" not in e["payload"] for e in status_events[:-1])


async def test_winning_line_null_while_game_running_and_after_undo(app, client, games_api, monkeypatch):
    _force_black(monkeypatch)
    app.state.adapter = games_api.FakeAdapter()
    await games_api.seed_login(app, client)
    gid = (
        await client.post("/api/games", json={"opponent": {"kind": "engine", "levelId": "novice"}})
    ).json()["id"]
    st = await games_api.wait_settled(client, gid)
    assert st["winning_line"] is None  # партия идёт

    await _play_black_five(client, games_api, gid)
    st = await games_api.wait_settled(client, gid)
    assert st["status"] == "finished_black" and st["winning_line"] is not None

    un = (await client.post(f"/api/games/{gid}/undo")).json()  # дефолтная политика: после конца можно
    assert un["status"] == "awaiting_move" and un["winning_line"] is None
```

- [ ] **Step 2: Убедиться, что падают**

Run: `uv run pytest tests/api/test_games_winning_line.py -q`
Expected: KeyError `'winning_line'` (поля в state нет).

- [ ] **Step 3: Реализация**

`backend/app/routers/games.py` — импорт и `_state`:

```python
from ..domain.rules import winning_line  # GameStatus уже импортируется из ..domain.values


def _state(game, user_id: int, hub) -> dict:
    fb = game.forbidden_log.get(str(len(game.moves)), [])
    wl = (
        winning_line([tuple(m) for m in game.moves])
        if GameStatus(game.status).is_finished
        else None
    )
    return {
        "id": game.id,
        "owner_id": game.owner_id,
        "controllers": _public_controllers(game.controllers),
        "your_color": _your_color(game.controllers, user_id),
        "status": game.status,
        "moves": game.moves,
        "undo_count": game.undo_count,
        "cursor": hub.cursor(game.id),
        "forbidden": fb,
        "winning_line": [list(p) for p in wl] if wl is not None else None,
    }
```

`backend/app/game/service.py` — импорт `winning_line` из `..domain.rules` (рядом с `outcome_after`), хелпер на уровне модуля и два места публикации финального `status`:

```python
def _final_status_payload(game: Game) -> dict:
    """Payload финального status: статус + winning_line (ничья линии не имеет → без поля)."""
    payload: dict = {"status": game.status}
    wl = winning_line([tuple(m) for m in game.moves])
    if wl is not None:
        payload["winning_line"] = [list(p) for p in wl]
    return payload
```

В `advance` (ветка `outcome is not None`):

```python
game.status = outcome.value
self._hub.publish(game.id, "status", _final_status_payload(game))
```

В `submit_move` (ветка `is_finished`):

```python
if GameStatus(game.status).is_finished:  # ход человека завершил партию — фона не будет
    self._hub.publish(game.id, "status", _final_status_payload(game))
```

Нефинальные публикации `status` (`awaiting_move`, `opponent_thinking`) НЕ трогать.

- [ ] **Step 4: Зелёные + полный прогон бэка**

Run: `uv run pytest -q` (последовательно!) → все зелёные.
Run: `uv run ruff check app tests scripts && uv run ruff format app tests scripts` → чисто.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/games.py backend/app/game/service.py backend/tests/api/test_games_winning_line.py
git commit -m "feat(rj-p82): winning_line в state и payload финального status-события"
```

---

### Task 3: Фронт — типы контракта и API-обёртки

**Files:**
- Create: `frontend/src/game/types.ts`
- Create: `frontend/src/game/api.ts`

Тонкие декларации без логики — собственных тестов нет, поведение покрывается тестами reducer/useGame/GamePage (Tasks 5/7/9), где msw проверяет реальные пути и тела.

- [ ] **Step 1: `frontend/src/game/types.ts`**

```ts
// Зеркало бэк-контракта (спека §«Контракт бэка глазами фронта»). snake_case — как на проводе.
export type Point = [number, number];
export type Color = "black" | "white";
export type GameStatus =
  | "awaiting_move"
  | "opponent_thinking"
  | "finished_black"
  | "finished_white"
  | "finished_draw";

export type ControllerDTO = { kind: "user" } | { kind: "engine"; levelId: string };

export type GameStateDTO = {
  id: string;
  owner_id: number;
  controllers: Partial<Record<Color, ControllerDTO>>;
  your_color: Color | null;
  status: GameStatus;
  moves: Point[];
  undo_count: number;
  cursor: number;
  forbidden: Point[];
  winning_line: Point[] | null;
};

export type LevelDTO = { id: string; name: string };

export type GameEventMessage =
  | { seq: number; type: "move"; payload: { by: Color; point: Point; move_index: number } }
  | { seq: number; type: "status"; payload: { status: GameStatus; winning_line?: Point[] } }
  | { seq: number; type: "forbidden"; payload: { points: Point[] } }
  | { seq: number; type: "undo"; payload: { move_count: number } }
  | { seq: number; type: "error"; payload: { message: string } }
  | { seq: number; type: "reset"; payload: Record<string, never> };
```

- [ ] **Step 2: `frontend/src/game/api.ts`**

```ts
import { apiRequest } from "../api/client";
import type { GameStateDTO, LevelDTO } from "./types";

export function createGame(levelId: string): Promise<GameStateDTO> {
  return apiRequest<GameStateDTO>("POST", "/api/games", { opponent: { kind: "engine", levelId } });
}

export function getGame(id: string): Promise<GameStateDTO> {
  return apiRequest<GameStateDTO>("GET", `/api/games/${id}`);
}

export function postMove(id: string, x: number, y: number): Promise<{ accepted: boolean }> {
  return apiRequest<{ accepted: boolean }>("POST", `/api/games/${id}/move`, { x, y });
}

export function postUndo(id: string): Promise<GameStateDTO> {
  return apiRequest<GameStateDTO>("POST", `/api/games/${id}/undo`);
}

export function getLevels(): Promise<LevelDTO[]> {
  return apiRequest<LevelDTO[]>("GET", "/api/levels");
}
```

- [ ] **Step 3: Компиляция и коммит**

Run (из `frontend/`): `npx tsc --noEmit` → чисто.

```bash
git add frontend/src/game/types.ts frontend/src/game/api.ts
git commit -m "feat(rj-p82): типы игрового контракта и API-обёртки"
```

---

### Task 4: Фронт — `legality.ts` (чистое зеркало правил ввода)

**Files:**
- Create: `frontend/src/game/legality.ts`
- Test: `frontend/src/game/legality.test.ts`

`GameView` нужен раньше редьюсера — в этой задаче создаётся и тип (в `reducer.ts` он будет дополнен функциями в Task 5; здесь объявить его в `types.ts` НЕЛЬЗЯ — это вью-модель, не провод). Решение: `GameView` живёт в `frontend/src/game/view.ts` (отдельный файл, без логики), `legality.ts` и `reducer.ts` импортируют оттуда — без циклов.

- [ ] **Step 1: `frontend/src/game/view.ts`**

```ts
import type { Color, GameStatus, Point } from "./types";

// Вью-модель партии (camelCase). pendingIndex — индекс неподтверждённого
// оптимистичного хода в moves (он уже лежит в массиве), null — нет pending.
export type GameView = {
  id: string;
  yourColor: Color | null;
  status: GameStatus;
  moves: Point[];
  pendingIndex: number | null;
  forbidden: Point[];
  winningLine: Point[] | null;
  cursor: number;
  opponentLevelId: string | null;
};
```

- [ ] **Step 2: Failing-тесты `frontend/src/game/legality.test.ts`**

```ts
import { it, expect, describe } from "vitest";
import { canPlay, canUndo, colorToMove, openingZone, pointLabel } from "./legality";
import type { GameView } from "./view";
import type { Point } from "./types";

const base: GameView = {
  id: "g1", yourColor: "black", status: "awaiting_move",
  moves: [[7, 7], [6, 6]], pendingIndex: null, forbidden: [],
  winningLine: null, cursor: 2, opponentLevelId: "novice",
};
const v = (over: Partial<GameView>): GameView => ({ ...base, ...over });

describe("colorToMove", () => {
  it("чётное число камней → чёрные, нечётное → белые", () => {
    expect(colorToMove(0)).toBe("black");
    expect(colorToMove(1)).toBe("white");
    expect(colorToMove(2)).toBe("black");
  });
});

describe("openingZone", () => {
  it("ход №1 → 3×3 вокруг центра", () => {
    const z = openingZone(1)!;
    expect(z).toHaveLength(9);
    expect(z).toContainEqual([6, 6]);
    expect(z).not.toContainEqual([5, 5]);
  });
  it("ход №2 → 5×5", () => {
    const z = openingZone(2)!;
    expect(z).toHaveLength(25);
    expect(z).toContainEqual([5, 5]);
    expect(z).not.toContainEqual([4, 7]);
  });
  it("ход №3+ → null (без ограничений)", () => {
    expect(openingZone(3)).toBeNull();
    expect(openingZone(0)).not.toBeNull(); // в партии не встречается (центр предзаполнен), но геометрия честная
  });
});

describe("canPlay", () => {
  it("свободная точка в свой ход (зона 5×5, ход №2) — можно", () => {
    expect(canPlay(v({}), [8, 7])).toBe(true);
  });
  it("занято — нельзя", () => expect(canPlay(v({}), [7, 7])).toBe(false));
  it("вне дебютной зоны (ход №2, 5×5) — нельзя", () => expect(canPlay(v({}), [1, 1])).toBe(false));
  it("после дебюта зона снята", () => {
    const view = v({ moves: [[7, 7], [6, 6], [8, 8], [9, 9]] }); // 4 камня → ход №4, зоны нет
    expect(canPlay(view, [1, 1])).toBe(true);
  });
  it("фол-точка — нельзя", () => {
    const view = v({ moves: [[7, 7], [6, 6], [8, 8], [9, 9]], forbidden: [[1, 1]] });
    expect(canPlay(view, [1, 1])).toBe(false);
  });
  it("не твоя очередь — нельзя", () => {
    expect(canPlay(v({ moves: [[7, 7]] }), [6, 6])).toBe(false); // 1 камень → ход белых, мы чёрные
  });
  it("соперник думает / партия кончена / pending — нельзя", () => {
    expect(canPlay(v({ status: "opponent_thinking" }), [8, 7])).toBe(false);
    expect(canPlay(v({ status: "finished_black" }), [8, 7])).toBe(false);
    expect(canPlay(v({ pendingIndex: 1 }), [8, 7])).toBe(false);
  });
  it("за доской — нельзя", () => expect(canPlay(v({}), [15, 0] as Point)).toBe(false));
});

describe("canUndo (зеркало undo_truncate: чёрным нужно ≥3 камней, белым ≥2)", () => {
  it("чёрные: 2 камня — нечего, 3 — можно", () => {
    expect(canUndo(v({ moves: [[7, 7], [6, 6]] }))).toBe(false);
    expect(canUndo(v({ moves: [[7, 7], [6, 6], [8, 8]], status: "opponent_thinking" }))).toBe(false); // думает — нельзя
    expect(canUndo(v({ moves: [[7, 7], [6, 6], [8, 8]] }))).toBe(true);
  });
  it("белые: 1 камень — нечего, 2 — можно", () => {
    expect(canUndo(v({ yourColor: "white", moves: [[7, 7]] }))).toBe(false);
    expect(canUndo(v({ yourColor: "white", moves: [[7, 7], [6, 6]] }))).toBe(true);
  });
  it("после конца партии — можно (дефолтная политика), при pending — нельзя", () => {
    expect(canUndo(v({ status: "finished_black", moves: [[7, 7], [6, 6], [8, 8]] }))).toBe(true);
    expect(canUndo(v({ pendingIndex: 2, moves: [[7, 7], [6, 6], [8, 8]] }))).toBe(false);
  });
});

describe("pointLabel", () => {
  it("колонка A–O по x, строка y+1", () => {
    expect(pointLabel([0, 0])).toBe("A1");
    expect(pointLabel([7, 7])).toBe("H8");
    expect(pointLabel([14, 14])).toBe("O15");
  });
});
```

- [ ] **Step 3: Убедиться, что падают**

Run (из `frontend/`): `npx vitest run src/game/legality.test.ts`
Expected: FAIL — модуль `./legality` не существует.

- [ ] **Step 4: Реализация `frontend/src/game/legality.ts`**

```ts
// Чистое зеркало серверных правил ввода (app/domain/{opening,game}.py) — для UX.
// Сервер остаётся последней инстанцией; рассинхрон лечится ресинхроном (спека).
import type { Color, Point } from "./types";
import type { GameView } from "./view";

export const BOARD_SIZE = 15;
const CX = 7; // центр (7,7) предзаполнен при создании партии

export function colorToMove(movesCount: number): Color {
  return movesCount % 2 === 0 ? "black" : "white";
}

export function openingZone(moveCount: number): Point[] | null {
  // зеркало opening_zone: 1 → 3×3, 2 → 5×5, дальше без ограничений
  const radius = moveCount === 0 ? 0 : moveCount === 1 ? 1 : moveCount === 2 ? 2 : null;
  if (radius === null) return null;
  const pts: Point[] = [];
  for (let y = CX - radius; y <= CX + radius; y++)
    for (let x = CX - radius; x <= CX + radius; x++) pts.push([x, y]);
  return pts;
}

const has = (pts: Point[], [x, y]: Point) => pts.some(([px, py]) => px === x && py === y);

export function canPlay(view: GameView, point: Point): boolean {
  const [x, y] = point;
  if (view.status !== "awaiting_move" || view.pendingIndex !== null) return false;
  if (view.yourColor === null || colorToMove(view.moves.length) !== view.yourColor) return false;
  if (x < 0 || x >= BOARD_SIZE || y < 0 || y >= BOARD_SIZE) return false;
  if (has(view.moves, point) || has(view.forbidden, point)) return false;
  const zone = openingZone(view.moves.length);
  return zone === null || has(zone, point);
}

export function canUndo(view: GameView): boolean {
  // зеркало undo_truncate (preset=1): нужен индекс k ≥ 1 чётности своего цвета
  if (view.pendingIndex !== null || view.status === "opponent_thinking") return false;
  if (view.yourColor === null) return false;
  return view.moves.length >= (view.yourColor === "black" ? 3 : 2);
}

export function pointLabel([x, y]: Point): string {
  return String.fromCharCode(65 + x) + String(y + 1); // A–O + 1–15 (как в прототипе)
}
```

- [ ] **Step 5: Зелёные и коммит**

Run: `npx vitest run src/game/legality.test.ts` → PASS. `npx tsc --noEmit` → чисто.

```bash
git add frontend/src/game/view.ts frontend/src/game/legality.ts frontend/src/game/legality.test.ts
git commit -m "feat(rj-p82): legality — чистое зеркало правил ввода (зоны, фолы, очерёдность, undo)"
```

---

### Task 5: Фронт — `reducer.ts` (применение SSE-событий)

**Files:**
- Create: `frontend/src/game/reducer.ts`
- Test: `frontend/src/game/reducer.test.ts`

- [ ] **Step 1: Failing-тесты `frontend/src/game/reducer.test.ts`**

```ts
import { it, expect, describe } from "vitest";
import { applyEvent, fromState, placePending } from "./reducer";
import type { GameView } from "./view";
import type { GameEventMessage, GameStateDTO } from "./types";

const dto: GameStateDTO = {
  id: "g1", owner_id: 1,
  controllers: { black: { kind: "user" }, white: { kind: "engine", levelId: "novice" } },
  your_color: "black", status: "awaiting_move",
  moves: [[7, 7], [6, 6]], undo_count: 0, cursor: 5, forbidden: [[5, 5]], winning_line: null,
};
const view = (): GameView => fromState(dto);
const ev = (e: GameEventMessage) => e;

describe("fromState", () => {
  it("snake_case → вью-модель; levelId движка извлечён", () => {
    const v = view();
    expect(v).toMatchObject({
      id: "g1", yourColor: "black", status: "awaiting_move", cursor: 5,
      pendingIndex: null, winningLine: null, opponentLevelId: "novice",
    });
    expect(v.moves).toEqual([[7, 7], [6, 6]]);
    expect(v.forbidden).toEqual([[5, 5]]);
  });
});

describe("правило курсора", () => {
  it("seq ≤ cursor — дубль реплея, игнор (state не меняется)", () => {
    const v = view();
    const r = applyEvent(v, ev({ seq: 5, type: "forbidden", payload: { points: [[1, 1]] } }));
    expect(r).toBe(v);
  });
  it("seq == cursor+1 — применить, cursor сдвинут", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "forbidden", payload: { points: [[1, 1]] } }));
    expect(r).not.toBe("resync");
    expect((r as GameView).cursor).toBe(6);
    expect((r as GameView).forbidden).toEqual([[1, 1]]);
  });
  it("seq > cursor+1 — пропуск событий → resync", () => {
    expect(applyEvent(view(), ev({ seq: 8, type: "forbidden", payload: { points: [] } }))).toBe("resync");
  });
});

describe("move", () => {
  it("чужой ход: move_index == moves.length → дорисовать, forbidden обнулён", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 2 } })) as GameView;
    expect(r.moves).toEqual([[7, 7], [6, 6], [8, 8]]);
    expect(r.forbidden).toEqual([]); // позиция сменилась; актуальный набор придёт forbidden-событием
  });
  it("своё подтверждение: совпали точка и АБСОЛЮТНЫЙ индекс pending → pending снят, камень остаётся", () => {
    const pending = placePending(view(), [8, 8]); // pendingIndex=2
    const r = applyEvent(pending, ev({ seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 2 } })) as GameView;
    expect(r.pendingIndex).toBeNull();
    expect(r.moves).toHaveLength(3); // не задвоился
  });
  it("несоответствие индекса (рассинхрон) → resync", () => {
    expect(applyEvent(view(), ev({ seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 7 } }))).toBe("resync");
  });
});

describe("status / forbidden / undo / reset / error", () => {
  it("status без winning_line — линия не трогается", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "status", payload: { status: "opponent_thinking" } })) as GameView;
    expect(r.status).toBe("opponent_thinking");
    expect(r.winningLine).toBeNull();
  });
  it("финальный status с winning_line — линия установлена", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "status", payload: { status: "finished_black", winning_line: [[7, 7], [8, 8]] } })) as GameView;
    expect(r.status).toBe("finished_black");
    expect(r.winningLine).toEqual([[7, 7], [8, 8]]);
  });
  it("undo: усечение до move_count, статус awaiting_move, pending/линия/фолы сняты", () => {
    const finished: GameView = { ...view(), status: "finished_black", winningLine: [[7, 7]], pendingIndex: 1 };
    const r = applyEvent(finished, ev({ seq: 6, type: "undo", payload: { move_count: 1 } })) as GameView;
    expect(r.moves).toEqual([[7, 7]]);
    expect(r).toMatchObject({ status: "awaiting_move", pendingIndex: null, winningLine: null, forbidden: [] });
  });
  it("reset → resync", () => {
    expect(applyEvent(view(), ev({ seq: 6, type: "reset", payload: {} }))).toBe("resync");
  });
  it("error — состояние не меняется, кроме курсора (сообщение — забота useGame)", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "error", payload: { message: "x" } })) as GameView;
    expect(r.cursor).toBe(6);
    expect(r.moves).toEqual(view().moves);
  });
});

describe("placePending", () => {
  it("кладёт камень в конец и помечает pending", () => {
    const r = placePending(view(), [8, 8]);
    expect(r.moves).toEqual([[7, 7], [6, 6], [8, 8]]);
    expect(r.pendingIndex).toBe(2);
  });
});
```

- [ ] **Step 2: Убедиться, что падают**

Run: `npx vitest run src/game/reducer.test.ts` → FAIL (модуля нет).

- [ ] **Step 3: Реализация `frontend/src/game/reducer.ts`**

```ts
// Чистый редьюсер SSE-событий (спека §«Контракт бэка», §«Поток данных»). Без I/O.
import type { GameEventMessage, GameStateDTO, Point } from "./types";
import type { GameView } from "./view";

export function fromState(st: GameStateDTO): GameView {
  const engine = Object.values(st.controllers).find((c) => c.kind === "engine");
  return {
    id: st.id,
    yourColor: st.your_color,
    status: st.status,
    moves: st.moves.map(([x, y]) => [x, y] as Point),
    pendingIndex: null,
    forbidden: st.forbidden.map(([x, y]) => [x, y] as Point),
    winningLine: st.winning_line?.map(([x, y]) => [x, y] as Point) ?? null,
    cursor: st.cursor,
    opponentLevelId: engine?.kind === "engine" ? engine.levelId : null,
  };
}

export function placePending(v: GameView, point: Point): GameView {
  return { ...v, moves: [...v.moves, point], pendingIndex: v.moves.length };
}

const same = (a: Point, b: Point) => a[0] === b[0] && a[1] === b[1];

export function applyEvent(v: GameView, ev: GameEventMessage): GameView | "resync" {
  if (ev.seq <= v.cursor) return v; // дубль реплея — идемпотентный игнор
  if (ev.seq > v.cursor + 1) return "resync"; // пропуск событий
  const base = { ...v, cursor: ev.seq };
  switch (ev.type) {
    case "move": {
      const { point, move_index } = ev.payload;
      const pt: Point = [point[0], point[1]];
      if (base.pendingIndex !== null && move_index === base.pendingIndex && same(base.moves[base.pendingIndex], pt)) {
        return { ...base, pendingIndex: null, forbidden: [] }; // подтверждение оптимистичного
      }
      if (base.pendingIndex === null && move_index === base.moves.length) {
        return { ...base, moves: [...base.moves, pt], forbidden: [] };
      }
      return "resync"; // индекс не сошёлся — состояние устарело
    }
    case "status":
      return {
        ...base,
        status: ev.payload.status,
        winningLine: ev.payload.winning_line?.map(([x, y]) => [x, y] as Point) ?? base.winningLine,
      };
    case "forbidden":
      return { ...base, forbidden: ev.payload.points.map(([x, y]) => [x, y] as Point) };
    case "undo":
      return {
        ...base,
        moves: base.moves.slice(0, ev.payload.move_count),
        status: "awaiting_move",
        pendingIndex: null,
        winningLine: null,
        forbidden: [],
      };
    case "reset":
      return "resync";
    case "error":
      return base; // курсор сдвинут; сообщение пользователю — забота useGame
  }
}
```

- [ ] **Step 4: Зелёные и коммит**

Run: `npx vitest run src/game/reducer.test.ts` → PASS. `npx tsc --noEmit` → чисто.

```bash
git add frontend/src/game/reducer.ts frontend/src/game/reducer.test.ts
git commit -m "feat(rj-p82): редьюсер SSE-событий — курсор, pending, undo, resync-сигнал"
```

---

### Task 6: Фронт — фейк EventSource для jsdom

**Files:**
- Create: `frontend/src/test/eventsource.ts`
- Modify: `frontend/src/test/setup.ts` (сброс глобальных стабов между тестами)

jsdom не реализует EventSource. Фейк регистрирует инстансы, умеет эмитить именованные события и имитировать разрыв. Это тестовая утилита — проверяется использованием в Task 7 (отдельные тесты не нужны), но компилироваться обязана строго.

- [ ] **Step 1: `frontend/src/test/eventsource.ts`**

```ts
import { vi } from "vitest";

/** Фейк EventSource: эмит именованных событий + имитация разрыва (onerror). */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static last(): FakeEventSource {
    const inst = FakeEventSource.instances.at(-1);
    if (!inst) throw new Error("FakeEventSource: ни одного инстанса не создано");
    return inst;
  }
  static reset() {
    FakeEventSource.instances = [];
  }

  url: string;
  readyState = 1; // OPEN
  onerror: ((e: Event) => void) | null = null;
  private listeners = new Map<string, Set<(e: MessageEvent) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(fn);
  }

  close() {
    this.readyState = 2; // CLOSED
  }

  /** Доставить именованное SSE-событие (data — объект {seq,type,payload}, сериализуется как на проводе). */
  emit(type: string, data: unknown) {
    const e = new MessageEvent(type, { data: JSON.stringify(data) });
    this.listeners.get(type)?.forEach((fn) => fn(e));
  }

  /** Имитация разрыва соединения. */
  fail() {
    this.onerror?.(new Event("error"));
  }
}

export function installFakeEventSource() {
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
}
```

- [ ] **Step 2: Сброс стабов в `frontend/src/test/setup.ts`**

В существующий `afterEach` (там уже `server.resetHandlers()` и сброс 401-обработчика) добавить строку и импорт `vi` из vitest:

```ts
import { afterAll, afterEach, beforeAll, vi } from "vitest";
// ...
afterEach(() => {
  server.resetHandlers();
  setUnauthorizedHandler(() => {});
  vi.unstubAllGlobals(); // стаб EventSource не утекает между тестами (ревью плана, M3)
});
```

- [ ] **Step 3: Компиляция и коммит**

Run: `npx tsc --noEmit` → чисто. `npx vitest run` → существующие тесты зелёные.

```bash
git add frontend/src/test/eventsource.ts frontend/src/test/setup.ts
git commit -m "test(rj-p82): фейк EventSource для jsdom (эмит событий, имитация разрыва)"
```

---

### Task 7: Фронт — хук `useGame` (I/O-оркестрация)

**Files:**
- Create: `frontend/src/game/useGame.ts`
- Test: `frontend/src/game/useGame.test.tsx`

- [ ] **Step 1: Failing-тесты `frontend/src/game/useGame.test.tsx`**

```tsx
import { renderHook, act, waitFor } from "@testing-library/react";
import { it, expect, beforeEach, vi } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { FakeEventSource, installFakeEventSource } from "../test/eventsource";
import { setUnauthorizedHandler } from "../api/client";
import { useGame } from "./useGame";
import type { GameStateDTO } from "./types";

const state = (over: Partial<GameStateDTO> = {}): GameStateDTO => ({
  id: "g1", owner_id: 1,
  controllers: { black: { kind: "user" }, white: { kind: "engine", levelId: "novice" } },
  your_color: "black", status: "awaiting_move",
  moves: [[7, 7], [6, 6]], undo_count: 0, cursor: 5, forbidden: [], winning_line: null,
  ...over,
});
const meOk = http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "a", role: "user" }));

beforeEach(() => {
  installFakeEventSource();
  FakeEventSource.reset();
});

it("старт: GET → view; EventSource открыт со since = state.cursor из GET-ответа", async () => {
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view?.moves).toHaveLength(2));
  expect(FakeEventSource.last().url).toBe("/api/games/g1/events?since=5");
});

it("SSE move соперника дорисовывается", async () => {
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  act(() => FakeEventSource.last().emit("move", { seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 2 } }));
  expect(result.current.view?.moves).toHaveLength(3);
});

it("оптимистичный ход: камень встаёт до ответа сервера; событие снимает pending раньше 202", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  server.use(
    http.get("/api/games/g1", () => HttpResponse.json(state())),
    http.post("/api/games/g1/move", async () => {
      await gate; // 202 задерживаем — своё move-событие придёт раньше (штатная гонка, спека M1)
      return HttpResponse.json({ accepted: true }, { status: 202 });
    }),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  let done!: Promise<void>;
  act(() => { done = result.current.play(8, 7); }); // ход №2 — зона 5×5, (8,7) легален
  await waitFor(() => expect(result.current.view?.pendingIndex).toBe(2)); // камень встал, POST ещё висит
  act(() => FakeEventSource.last().emit("move", { seq: 6, type: "move", payload: { by: "black", point: [8, 7], move_index: 2 } }));
  expect(result.current.view?.pendingIndex).toBeNull(); // подтверждён событием ДО 202
  release();
  await act(async () => { await done; });
  expect(result.current.notice).toBeNull(); // исход POST после подтверждения — игнор
  expect(result.current.view?.moves).toHaveLength(3);
});

it("разрыв SSE при живом 202: pending переживает reconnect и снимается реплеем", async () => {
  server.use(
    meOk,
    http.get("/api/games/g1", () => HttpResponse.json(state())),
    http.post("/api/games/g1/move", () => HttpResponse.json({ accepted: true }, { status: 202 })),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  await act(async () => { await result.current.play(8, 7); }); // 202 пришёл, своё событие — нет
  expect(result.current.view?.pendingIndex).toBe(2);
  act(() => FakeEventSource.last().fail());
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2)); // reconnect с cursor=5
  act(() => FakeEventSource.last().emit("move", { seq: 6, type: "move", payload: { by: "black", point: [8, 7], move_index: 2 } })); // реплей с буфера
  expect(result.current.view?.pendingIndex).toBeNull();
  expect(result.current.view?.moves).toHaveLength(3);
});

it("отказ POST до подтверждения: откат, ресинхрон, нейтральное сообщение", async () => {
  let gets = 0;
  server.use(
    http.get("/api/games/g1", () => {
      gets += 1;
      return HttpResponse.json(state()); // ресинхрон вернёт исходные 2 камня
    }),
    http.post("/api/games/g1/move", () => HttpResponse.json({ detail: "opponent_thinking" }, { status: 409 })),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  await act(async () => { await result.current.play(8, 7); });
  expect(result.current.view?.moves).toHaveLength(2); // откатился
  expect(result.current.view?.pendingIndex).toBeNull();
  expect(result.current.notice).toBe("Доска обновлена — ход не прошёл");
  expect(gets).toBe(2); // стартовый + ресинхрон
});

it("нелегальный клик не ходит (POST нет)", async () => {
  let posts = 0;
  server.use(
    http.get("/api/games/g1", () => HttpResponse.json(state())),
    http.post("/api/games/g1/move", () => {
      posts += 1;
      return HttpResponse.json({ accepted: true }, { status: 202 });
    }),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  await act(async () => { await result.current.play(7, 7); }); // занято
  await act(async () => { await result.current.play(1, 1); }); // вне зоны 5×5
  expect(posts).toBe(0);
  expect(result.current.view?.moves).toHaveLength(2);
});

it("undo: ответ-state заменяет вью целиком", async () => {
  server.use(
    http.get("/api/games/g1", () => HttpResponse.json(state({ moves: [[7, 7], [6, 6], [8, 7], [0, 0]], cursor: 9 }))),
    http.post("/api/games/g1/undo", () => HttpResponse.json(state({ moves: [[7, 7], [6, 6]], cursor: 11 }))),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view?.moves).toHaveLength(4));
  await act(async () => { await result.current.undoMove(); });
  expect(result.current.view?.moves).toHaveLength(2);
  expect(result.current.view?.cursor).toBe(11);
});

it("пропуск seq → ресинхрон через GET", async () => {
  let gets = 0;
  server.use(http.get("/api/games/g1", () => {
    gets += 1;
    return HttpResponse.json(state({ cursor: gets === 1 ? 5 : 9 }));
  }));
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  await act(async () => {
    FakeEventSource.last().emit("forbidden", { seq: 9, type: "forbidden", payload: { points: [] } }); // 5 → 9: дыра
    await Promise.resolve();
  });
  await waitFor(() => expect(result.current.view?.cursor).toBe(9));
  expect(gets).toBe(2);
});

it("разрыв SSE: пауза → проверка сессии → новый EventSource с текущим курсором", async () => {
  server.use(meOk, http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result } = renderHook(() => useGame("g1", 0)); // reconnectDelayMs=0 — без таймеров
  await waitFor(() => expect(result.current.view).not.toBeNull());
  const first = FakeEventSource.last();
  act(() => {
    first.emit("move", { seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 2 } });
    first.fail();
  });
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
  expect(first.readyState).toBe(2); // старый закрыт
  expect(FakeEventSource.last().url).toBe("/api/games/g1/events?since=6"); // курсор актуальный
});

it("сессия отозвана: 401 на проверке → глобальный обработчик, реконнекта нет", async () => {
  const onUnauthorized = vi.fn();
  setUnauthorizedHandler(onUnauthorized);
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  // дефолтный msw-хендлер /api/auth/me — 401
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  act(() => FakeEventSource.last().fail());
  await waitFor(() => expect(onUnauthorized).toHaveBeenCalled());
  expect(FakeEventSource.instances).toHaveLength(1); // новый стрим не открыт
});

it("error-событие → ненавязчивое сообщение, состояние цело", async () => {
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  act(() => FakeEventSource.last().emit("error", { seq: 6, type: "error", payload: { message: "engine died" } }));
  expect(result.current.notice).toBe("Движок споткнулся — партия продолжится автоматически");
  expect(result.current.view?.moves).toHaveLength(2);
});

it("размонтирование закрывает стрим", async () => {
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result, unmount } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  unmount();
  expect(FakeEventSource.last().readyState).toBe(2);
});
```

- [ ] **Step 2: Убедиться, что падают**

Run: `npx vitest run src/game/useGame.test.tsx` → FAIL (модуля нет).

- [ ] **Step 3: Реализация `frontend/src/game/useGame.ts`**

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api/client";
import { getGame, postMove, postUndo } from "./api";
import { canPlay } from "./legality";
import { applyEvent, fromState, placePending } from "./reducer";
import type { GameEventMessage, Point } from "./types";
import type { GameView } from "./view";

const EVENT_TYPES = ["move", "status", "forbidden", "undo", "error", "reset"] as const;

/** Оркестрация партии: начальный GET, SSE с reconnect, оптимистичный ход, undo.
 *  Чистая логика — в reducer/legality; здесь только I/O и склейка (спека §«Поток данных»). */
export function useGame(gameId: string, reconnectDelayMs = 3000) {
  const [view, setView] = useState<GameView | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const viewRef = useRef<GameView | null>(null); // актуальное состояние для колбэков вне рендера
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);

  const commit = useCallback((v: GameView) => {
    viewRef.current = v;
    setView(v);
  }, []);

  const resync = useCallback(async () => {
    // сервер — источник истины; pending при ресинхроне сбрасывается вместе с заменой вью
    try {
      const st = await getGame(gameId);
      if (aliveRef.current) commit(fromState(st));
    } catch {
      if (aliveRef.current) setNotice("Не удалось загрузить партию");
    }
  }, [gameId, commit]);

  const handleEvent = useCallback(
    (ev: GameEventMessage) => {
      const cur = viewRef.current;
      if (!cur) return;
      if (ev.type === "error") setNotice("Движок споткнулся — партия продолжится автоматически");
      const next = applyEvent(cur, ev);
      if (next === "resync") void resync();
      else commit(next);
    },
    [resync, commit],
  );

  const connect = useCallback(
    (since: number) => {
      const es = new EventSource(`/api/games/${gameId}/events?since=${since}`);
      esRef.current = es;
      for (const t of EVENT_TYPES) {
        es.addEventListener(t, (e) => handleEvent(JSON.parse((e as MessageEvent).data) as GameEventMessage));
      }
      es.onerror = () => {
        es.close();
        timerRef.current = setTimeout(() => {
          void (async () => {
            try {
              // проверка сессии БЕЗ skipAuthRedirect: отозвана → глобальный 401-редирект,
              // вечный реконнект-цикл исключён (мастер-спека §10)
              await apiRequest("GET", "/api/auth/me");
            } catch {
              return; // сессии нет — реконнект не возобновляем
            }
            if (aliveRef.current) connect(viewRef.current?.cursor ?? since);
          })();
        }, reconnectDelayMs);
      };
    },
    [gameId, handleEvent, reconnectDelayMs],
  );

  useEffect(() => {
    aliveRef.current = true;
    void (async () => {
      try {
        const st = await getGame(gameId);
        if (!aliveRef.current) return;
        commit(fromState(st));
        connect(st.cursor); // курсор первого подключения — из GET-ответа (спека, M2)
      } catch {
        if (aliveRef.current) setNotice("Не удалось загрузить партию");
      }
    })();
    return () => {
      aliveRef.current = false;
      esRef.current?.close();
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [gameId, connect, commit]);

  const play = useCallback(
    async (x: number, y: number) => {
      const cur = viewRef.current;
      const pt: Point = [x, y];
      if (!cur || !canPlay(cur, pt)) return; // нелегальный клик — тишина (ghost его и не покажет)
      commit(placePending(cur, pt));
      try {
        await postMove(gameId, x, y); // 202; подтверждение — своё SSE-move (могло прийти раньше ответа)
      } catch {
        if (!aliveRef.current) return;
        if (viewRef.current?.pendingIndex !== null) {
          // ещё не подтверждён → рассинхрон: откат + истина с сервера (спека, доктрина отказов)
          setNotice("Доска обновлена — ход не прошёл");
          await resync();
        }
        // уже подтверждён событием → исход POST игнорируем (первый из двух исходов решает)
      }
    },
    [gameId, commit, resync],
  );

  const undoMove = useCallback(async () => {
    try {
      const st = await postUndo(gameId); // ответ undo — полный state (cursor консистентен событиям)
      if (aliveRef.current) commit(fromState(st));
    } catch {
      if (!aliveRef.current) return;
      setNotice("Доска обновлена — действие не прошло");
      await resync();
    }
  }, [gameId, commit, resync]);

  const dismissNotice = useCallback(() => setNotice(null), []);

  return { view, notice, play, undoMove, dismissNotice };
}
```

- [ ] **Step 4: Зелёные и коммит**

Run: `npx vitest run src/game/useGame.test.tsx` → PASS. Затем весь фронт: `npx vitest run` → PASS. `npx tsc --noEmit` → чисто.

```bash
git add frontend/src/game/useGame.ts frontend/src/game/useGame.test.tsx
git commit -m "feat(rj-p82): useGame — GET+SSE+reconnect, оптимистичный ход, undo, ресинхрон"
```

---

### Task 8: Фронт — компонент `Board` (гобан)

**Files:**
- Create: `frontend/src/assets/board_pine.jpg` (копия `prototype/assets/board_pine.jpg`)
- Create: `frontend/src/components/board/Board.tsx`
- Create: `frontend/src/components/board/Board.module.css`
- Test: `frontend/src/components/board/Board.test.tsx`

- [ ] **Step 1: Ассет**

```bash
mkdir -p frontend/src/assets && cp prototype/assets/board_pine.jpg frontend/src/assets/board_pine.jpg
```

- [ ] **Step 2: Failing-тесты `frontend/src/components/board/Board.test.tsx`**

```tsx
import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Board } from "./Board";
import type { Point } from "../../game/types";

const noop = () => {};
const allow = () => true;
const deny = () => false;

function renderBoard(over: Partial<Parameters<typeof Board>[0]> = {}) {
  const props = {
    moves: [[7, 7], [6, 6]] as Point[],
    forbidden: [] as Point[],
    zone: null as Point[] | null,
    winningLine: null as Point[] | null,
    ghostColor: "black" as const,
    canPlayAt: allow as (x: number, y: number) => boolean,
    onPlay: noop as (x: number, y: number) => void,
    ...over,
  };
  return render(<Board {...props} />);
}

it("рисует 225 узлов и камни позиции (чёрный/белый по чётности)", () => {
  renderBoard();
  expect(screen.getAllByRole("button")).toHaveLength(225);
  expect(screen.getByTestId("stone-7-7").className).toContain("black");
  expect(screen.getByTestId("stone-6-6").className).toContain("white");
});

it("клик по узлу зовёт onPlay с координатами", async () => {
  const onPlay = vi.fn();
  renderBoard({ onPlay });
  await userEvent.click(screen.getByRole("button", { name: "I8" })); // x=8,y=7
  expect(onPlay).toHaveBeenCalledWith(8, 7);
});

it("canPlayAt=false дизейблит узел — клик не проходит", async () => {
  const onPlay = vi.fn();
  renderBoard({ onPlay, canPlayAt: deny });
  expect(screen.getByRole("button", { name: "H8" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "H8" }));
  expect(onPlay).not.toHaveBeenCalled();
});

it("маркер последнего хода стоит на последнем камне", () => {
  renderBoard();
  expect(screen.getByTestId("last-6-6")).toBeInTheDocument();
  expect(screen.queryByTestId("last-7-7")).not.toBeInTheDocument();
});

it("фолы отмечены ✕", () => {
  renderBoard({ forbidden: [[5, 8]] as Point[] });
  expect(screen.getByTestId("forbid-5-8")).toHaveTextContent("✕");
});

it("рамка дебютной зоны видна, когда зона задана, и отсутствует без неё", () => {
  const zone: Point[] = [];
  for (let y = 5; y <= 9; y++) for (let x = 5; x <= 9; x++) zone.push([x, y]);
  const { rerender } = renderBoard({ zone });
  expect(screen.getByTestId("zone-frame")).toBeInTheDocument();
  rerender(
    <Board moves={[[7, 7]] as Point[]} forbidden={[]} zone={null} winningLine={null}
      ghostColor="black" canPlayAt={allow} onPlay={noop} />,
  );
  expect(screen.queryByTestId("zone-frame")).not.toBeInTheDocument();
});

it("выигрышная линия подсвечена меткой на каждом камне", () => {
  renderBoard({ winningLine: [[7, 7], [8, 8]] as Point[] });
  expect(screen.getByTestId("win-7-7")).toBeInTheDocument();
  expect(screen.getByTestId("win-8-8")).toBeInTheDocument();
});
```

- [ ] **Step 3: Убедиться, что падают**

Run: `npx vitest run src/components/board/Board.test.tsx` → FAIL (модуля нет).

- [ ] **Step 4: Реализация `frontend/src/components/board/Board.tsx`**

```tsx
import { pointLabel } from "../../game/legality";
import type { Color, Point } from "../../game/types";
import styles from "./Board.module.css";

// Геометрия гобана — пропорции прототипа (--step:38px, --pad:30px, бок 592px).
// Все позиции в процентах от квадрата → доска fluid без JS (спека §«Геометрия»).
const N = 15;
const PAD = 30 / 592;
const STEP = 38 / 592;
const HOSHI: Point[] = [[3, 3], [11, 3], [3, 11], [11, 11], [7, 7]];

const pos = (i: number) => `${(PAD + i * STEP) * 100}%`;
const at = ([x, y]: Point) => ({ left: pos(x), top: pos(y) }); // инлайн — значения из данных (конвенция)

const CELLS: Point[] = [];
for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) CELLS.push([x, y]);

type BoardProps = {
  moves: Point[];
  forbidden: Point[];
  zone: Point[] | null; // дебютная зона для рамки (null — рамки нет)
  winningLine: Point[] | null;
  ghostColor: Color; // цвет ходящего — для hover-превью
  canPlayAt: (x: number, y: number) => boolean;
  onPlay: (x: number, y: number) => void;
};

function zoneRect(zone: Point[]) {
  const xs = zone.map((p) => p[0]);
  const ys = zone.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const w = Math.max(...xs) - minX + 1;
  const h = Math.max(...ys) - minY + 1;
  return {
    left: `${(PAD + (minX - 0.5) * STEP) * 100}%`,
    top: `${(PAD + (minY - 0.5) * STEP) * 100}%`,
    width: `${w * STEP * 100}%`,
    height: `${h * STEP * 100}%`,
  };
}

export function Board({ moves, forbidden, zone, winningLine, ghostColor, canPlayAt, onPlay }: BoardProps) {
  const last = moves.at(-1);
  const lastIdx = moves.length - 1;
  return (
    <div className={styles.goban}>
      <div className={styles.gridLines} />
      {HOSHI.map((p) => (
        <div key={`h${p[0]}-${p[1]}`} className={styles.hoshi} style={at(p)} />
      ))}
      {zone && <div className={styles.zoneFrame} style={zoneRect(zone)} data-testid="zone-frame" />}
      {CELLS.map(([x, y]) => (
        <button
          key={`n${x}-${y}`}
          type="button"
          className={styles.node}
          style={at([x, y])}
          aria-label={pointLabel([x, y])}
          disabled={!canPlayAt(x, y)}
          onClick={() => onPlay(x, y)}
        >
          <span className={`${styles.ghost} ${ghostColor === "black" ? styles.ghostBlack : styles.ghostWhite}`} />
        </button>
      ))}
      {moves.map((m, i) => (
        <div
          key={`s${i}`}
          className={`${styles.stone} ${i % 2 === 0 ? styles.black : styles.white}`}
          style={at(m)}
          data-testid={`stone-${m[0]}-${m[1]}`}
        />
      ))}
      {last && (
        <div
          className={`${styles.last} ${lastIdx % 2 === 0 ? styles.lastOnBlack : styles.lastOnWhite}`}
          style={at(last)}
          data-testid={`last-${last[0]}-${last[1]}`}
        />
      )}
      {forbidden.map((p) => (
        <div key={`f${p[0]}-${p[1]}`} className={styles.forbid} style={at(p)} data-testid={`forbid-${p[0]}-${p[1]}`}>
          ✕
        </div>
      ))}
      {winningLine?.map((p) => (
        <div key={`w${p[0]}-${p[1]}`} className={styles.winMark} style={at(p)} data-testid={`win-${p[0]}-${p[1]}`} />
      ))}
    </div>
  );
}
```

- [ ] **Step 5: `frontend/src/components/board/Board.module.css`**

Порт `.goban`-блока прототипа; px → проценты от стороны гобана (592px): камень 32→5.4054%, узел 38→6.4189%, ghost 30→5.0676%, хоси 7→1.1824%, маркер 10→1.6892%, инсет сетки 30→5.0676%. Размер ✕ — контейнерные единицы (cqw), чтобы масштабировался с доской.

```css
/* Гобан по prototype/index.html §GAME (.goban и слои); наши дополнения: рамка
   дебютной зоны и метки выигрышной линии (реестр отличий — в спеке среза).
   Текстура: board_pine.jpg — Vecteezy free license, атрибуция на странице игры. */
@value lineInk, vermillion, shadow, fontSerif from "../../styles/tokens.module.css";

.goban {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  border-radius: 8px;
  container-type: inline-size; /* для cqw-размеров текстовых меток (✕) */
  background:
    linear-gradient(160deg, rgba(255, 250, 238, 0.1), rgba(214, 182, 134, 0.08)),
    url("../../assets/board_pine.jpg");
  background-size: cover;
  background-position: center;
  box-shadow: shadow, inset 0 0 0 2px rgba(150, 110, 60, 0.38), inset 0 2px 12px rgba(255, 248, 230, 0.45);
}
.goban::after { /* виньетка глубины поверх дерева — из прототипа */
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 8px;
  pointer-events: none;
  background: radial-gradient(125% 125% at 30% 18%, rgba(255, 250, 232, 0.18), rgba(120, 80, 40, 0) 52%, rgba(120, 82, 38, 0.07));
}
.gridLines {
  position: absolute;
  left: 5.0676%;
  top: 5.0676%;
  width: calc(89.8648% + 1px); /* +1px замыкает последнюю линию (приём прототипа) */
  height: calc(89.8648% + 1px);
  background-image:
    linear-gradient(lineInk 1px, transparent 1px),
    linear-gradient(90deg, lineInk 1px, transparent 1px);
  background-size: calc((100% - 1px) / 14) calc((100% - 1px) / 14);
}
.hoshi {
  position: absolute;
  width: 1.1824%;
  height: 1.1824%;
  border-radius: 50%;
  background: rgba(40, 28, 14, 0.7);
  transform: translate(-50%, -50%);
  z-index: 2;
}
.node {
  position: absolute;
  width: 6.4189%;
  height: 6.4189%;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  display: grid;
  place-items: center;
  z-index: 3;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
}
.node:disabled { cursor: default; }
.node:disabled .ghost { display: none; }
.node:hover .ghost { opacity: 0.5; }
.ghost {
  width: 79%; /* 30/38 от узла = 30px прототипа */
  height: 79%;
  border-radius: 50%;
  opacity: 0;
  transition: 0.12s;
  pointer-events: none;
}
.ghostBlack { background: radial-gradient(circle at 34% 28%, #5a554e, #15110d); }
.ghostWhite { background: radial-gradient(circle at 34% 28%, #fff, #cfc8b8); }
.stone {
  position: absolute;
  width: 5.4054%;
  height: 5.4054%;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  z-index: 4;
  animation: place 0.25s cubic-bezier(0.2, 0.8, 0.2, 1) both;
}
@keyframes place {
  from { transform: translate(-50%, -50%) scale(0.4); opacity: 0; }
  to { transform: translate(-50%, -50%) scale(1); opacity: 1; }
}
.black {
  background: radial-gradient(circle at 34% 28%, #5a554e 0%, #211d18 55%, #0d0b09 100%);
  box-shadow: 0 4px 7px -2px rgba(20, 12, 4, 0.6), inset 0 -3px 6px rgba(0, 0, 0, 0.5), inset 0 2px 3px rgba(255, 255, 255, 0.18);
}
.white {
  background: radial-gradient(circle at 34% 28%, #ffffff 0%, #f2ede1 50%, #cbc2af 100%);
  box-shadow: 0 4px 7px -2px rgba(20, 12, 4, 0.4), inset 0 -3px 6px rgba(120, 100, 70, 0.25), inset 0 2px 3px rgba(255, 255, 255, 0.8);
}
.last {
  position: absolute;
  width: 1.6892%;
  height: 1.6892%;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  z-index: 5;
  pointer-events: none;
}
.lastOnBlack { background: #e9dcc4; }
.lastOnWhite { background: vermillion; }
.forbid {
  position: absolute;
  transform: translate(-50%, -50%);
  z-index: 5;
  color: vermillion;
  font-weight: 700;
  font-family: fontSerif;
  font-size: 3.7cqw; /* 22/592 от стороны гобана */
  pointer-events: none;
  text-shadow: 0 1px 1px rgba(255, 240, 220, 0.6);
}
.winMark { /* наше дополнение: кольцо в киновари на камнях выигрышной линии */
  position: absolute;
  width: 5.4054%;
  height: 5.4054%;
  border-radius: 50%;
  border: 2px solid vermillion;
  transform: translate(-50%, -50%);
  z-index: 6;
  pointer-events: none;
  box-sizing: border-box;
}
.zoneFrame { /* наше дополнение: рамка дебютной зоны (вид утверждается на приёмке) */
  position: absolute;
  border: 1.5px dashed vermillion;
  border-radius: 6px;
  background: rgba(189, 51, 38, 0.04);
  z-index: 2;
  pointer-events: none;
  box-sizing: border-box;
}
```

- [ ] **Step 6: Зелёные и коммит**

Run: `npx vitest run src/components/board/Board.test.tsx` → PASS. `npx tsc --noEmit` → чисто.

```bash
git add frontend/src/assets/board_pine.jpg frontend/src/components/board/
git commit -m "feat(rj-p82): Board — DOM-гобан по прототипу (камни, ghost, фолы, зона, линия)"
```

---

### Task 9: Фронт — экран `GamePage`

**Files:**
- Create: `frontend/src/pages/GamePage.tsx`
- Create: `frontend/src/pages/GamePage.module.css`
- Test: `frontend/src/pages/GamePage.test.tsx`

- [ ] **Step 1: Failing-тесты `frontend/src/pages/GamePage.test.tsx`**

```tsx
import { it, expect, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import { FakeEventSource, installFakeEventSource } from "../test/eventsource";
import GamePage from "./GamePage";
import type { GameStateDTO } from "../game/types";

const levels = http.get("/api/levels", () =>
  HttpResponse.json([{ id: "novice", name: "Новичок" }, { id: "master", name: "Мастер" }]),
);
const state = (over: Partial<GameStateDTO> = {}): GameStateDTO => ({
  id: "g1", owner_id: 1,
  controllers: { black: { kind: "user" }, white: { kind: "engine", levelId: "novice" } },
  your_color: "black", status: "awaiting_move",
  moves: [[7, 7], [6, 6], [8, 7]], undo_count: 0, cursor: 7, forbidden: [], winning_line: null,
  ...over,
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/game/g1"]}>
      <Routes>
        <Route path="/game/:gameId" element={<GamePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  installFakeEventSource();
  FakeEventSource.reset();
});

it("панель: заголовок, чей ход, уровень по имени, цвет, № хода, лог", async () => {
  server.use(levels, http.get("/api/games/g1", () => HttpResponse.json(state())));
  renderPage();
  expect(await screen.findByText(/ты играешь чёрными/)).toBeInTheDocument();
  expect(screen.getByText("Ход соперника")).toBeInTheDocument(); // 3 камня → ход белых, мы чёрные
  expect(await screen.findByText("Новичок")).toBeInTheDocument();
  expect(screen.getByText("№3")).toBeInTheDocument();
  const log = screen.getByTestId("movelog");
  expect(log.textContent).toContain("3. ⚫ I8"); // новые сверху: I8 = (8,7)
  expect(log.firstChild?.textContent).toContain("3.");
});

it("свой ход: клик по свободной точке шлёт POST и рисует камень оптимистично", async () => {
  let posted: unknown = null;
  server.use(
    levels,
    http.get("/api/games/g1", () => HttpResponse.json(state({ moves: [[7, 7], [6, 6]], cursor: 5 }))),
    http.post("/api/games/g1/move", async ({ request }) => {
      posted = await request.json();
      return HttpResponse.json({ accepted: true }, { status: 202 });
    }),
  );
  renderPage();
  expect(await screen.findByText("Твой ход")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "I8" })); // (8,7) — в зоне 5×5
  await waitFor(() => expect(posted).toEqual({ x: 8, y: 7 }));
  expect(screen.getByTestId("stone-8-7")).toBeInTheDocument();
});

it("opponent_thinking: индикатор «соперник думает…», узлы заблокированы", async () => {
  server.use(levels, http.get("/api/games/g1", () => HttpResponse.json(state({ status: "opponent_thinking" }))));
  renderPage();
  expect(await screen.findByText(/соперник думает/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "A1" })).toBeDisabled();
});

it("финиш: текст победы, линия подсвечена; undo возвращает игру и гасит подсветку", async () => {
  const finished = state({
    status: "finished_black",
    moves: [[7, 7], [6, 6], [8, 7], [0, 0], [9, 7], [0, 1], [10, 7], [0, 2], [11, 7]],
    winning_line: [[7, 7], [8, 7], [9, 7], [10, 7], [11, 7]],
    cursor: 20,
  });
  server.use(
    levels,
    http.get("/api/games/g1", () => HttpResponse.json(finished)),
    http.post("/api/games/g1/undo", () =>
      HttpResponse.json(state({ moves: [[7, 7], [6, 6], [8, 7], [0, 0], [9, 7], [0, 1], [10, 7], [0, 2]], cursor: 22 })),
    ),
  );
  renderPage();
  expect(await screen.findByText("Победа чёрных ⚫")).toBeInTheDocument();
  expect(screen.getByTestId("win-9-7")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "A1" })).toBeDisabled(); // ввод заблокирован
  await userEvent.click(screen.getByRole("button", { name: /отменить/i }));
  await waitFor(() => expect(screen.queryByTestId("win-9-7")).not.toBeInTheDocument());
  expect(screen.getByText("Твой ход")).toBeInTheDocument();
});

it("undo задизейблен, когда откатывать нечего (чёрные, 2 камня)", async () => {
  server.use(levels, http.get("/api/games/g1", () => HttpResponse.json(state({ moves: [[7, 7], [6, 6]], cursor: 5 }))));
  renderPage();
  await screen.findByText("Твой ход");
  expect(screen.getByRole("button", { name: /отменить/i })).toBeDisabled();
});

it("рамка дебютной зоны видна на своём ходу №2 и не видна на чужом", async () => {
  server.use(levels, http.get("/api/games/g1", () => HttpResponse.json(state({ moves: [[7, 7], [6, 6]], cursor: 5 }))));
  renderPage();
  await screen.findByText("Твой ход");
  expect(screen.getByTestId("zone-frame")).toBeInTheDocument(); // ход №2 → 5×5
});

it("notice отображается и закрывается", async () => {
  server.use(
    levels,
    http.get("/api/games/g1", () => HttpResponse.json(state())),
  );
  renderPage();
  await screen.findByText(/ты играешь/);
  act(() => FakeEventSource.last().emit("error", { seq: 8, type: "error", payload: { message: "x" } }));
  expect(await screen.findByRole("status")).toHaveTextContent("Движок споткнулся");
  await userEvent.click(screen.getByRole("button", { name: "✕" }));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Убедиться, что падают**

Run: `npx vitest run src/pages/GamePage.test.tsx` → FAIL (модуля нет).

- [ ] **Step 3: Реализация `frontend/src/pages/GamePage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Board } from "../components/board/Board";
import { getLevels } from "../game/api";
import { canPlay, canUndo, colorToMove, openingZone, pointLabel } from "../game/legality";
import type { LevelDTO } from "../game/types";
import type { GameView } from "../game/view";
import { useGame } from "../game/useGame";
import styles from "./GamePage.module.css";

const COLOR_RU = { black: "чёрными", white: "белыми" } as const;

function turnText(view: GameView): string {
  switch (view.status) {
    case "finished_black":
      return "Победа чёрных ⚫";
    case "finished_white":
      return "Победа белых ⚪";
    case "finished_draw":
      return "Ничья";
    case "opponent_thinking":
      return "Ход соперника";
    case "awaiting_move":
      return colorToMove(view.moves.length) === view.yourColor ? "Твой ход" : "Ход соперника";
  }
}

export default function GamePage() {
  const { gameId } = useParams<{ gameId: string }>();
  const { view, notice, play, undoMove, dismissNotice } = useGame(gameId!);
  const [levels, setLevels] = useState<LevelDTO[]>([]);
  useEffect(() => {
    getLevels().then(setLevels).catch(() => {}); // имя уровня — украшение; ошибка не валит экран
  }, []);

  if (!view) return <div className={styles.loading}>{notice ?? "Загрузка…"}</div>;

  const myTurn = view.status === "awaiting_move" && colorToMove(view.moves.length) === view.yourColor;
  const zone = myTurn ? openingZone(view.moves.length) : null; // рамка видна только когда ввод за человеком
  const levelName = levels.find((l) => l.id === view.opponentLevelId)?.name ?? view.opponentLevelId ?? "—";
  const toMove = colorToMove(view.moves.length);

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>
        Партия · ты играешь {view.yourColor ? COLOR_RU[view.yourColor] : "—"}
      </div>
      <div className={styles.layout}>
        <div className={styles.boardShell}>
          <Board
            moves={view.moves}
            forbidden={view.forbidden}
            zone={zone}
            winningLine={view.winningLine}
            ghostColor={toMove}
            canPlayAt={(x, y) => canPlay(view, [x, y])}
            onPlay={play}
          />
        </div>
        <aside className={styles.panel}>
          {notice && (
            <div className={styles.notice} role="status">
              <span>{notice}</span>
              <button type="button" className={styles.noticeClose} onClick={dismissNotice} aria-label="✕">
                ✕
              </button>
            </div>
          )}
          <div className={styles.card}>
            <div className={styles.turn}>
              <span
                className={`${styles.bigstone} ${toMove === "black" ? styles.bigBlack : styles.bigWhite}`}
              />
              <div className={styles.who}>{turnText(view)}</div>
            </div>
            {view.status === "opponent_thinking" && (
              <div className={styles.thinking}>
                <span className={styles.dot} />
                <span className={styles.dot} />
                <span className={styles.dot} /> соперник думает…
              </div>
            )}
          </div>
          <div className={styles.card}>
            <div className={styles.kv}>
              <span className={styles.k}>Уровень</span>
              <span className={styles.levelPill}>{levelName}</span>
            </div>
            <div className={styles.kv}>
              <span className={styles.k}>Твой цвет</span>
              <span className={styles.v}>{view.yourColor === "black" ? "чёрные ⚫" : "белые ⚪"}</span>
            </div>
            <div className={styles.kv}>
              <span className={styles.k}>Ход</span>
              <span className={styles.v}>№{view.moves.length}</span>
            </div>
          </div>
          <div className={styles.controls}>
            <button type="button" className={styles.undoBtn} disabled={!canUndo(view)} onClick={() => void undoMove()}>
              ↶ Отменить
            </button>
          </div>
          <div className={styles.card}>
            <div className={styles.eyebrow}>Лог ходов</div>
            <div className={styles.movelog} data-testid="movelog">
              {view.moves
                .map((m, i) => ({ m, i }))
                .reverse()
                .map(({ m, i }) => (
                  <div key={i}>
                    {i + 1}. <b>{i % 2 === 0 ? "⚫" : "⚪"}</b> {pointLabel(m)}
                  </div>
                ))}
            </div>
          </div>
          <div className={styles.attr}>
            <a href="https://www.vecteezy.com/free-photos/wood" target="_blank" rel="noopener noreferrer">
              Wood Stock photos by Vecteezy
            </a>
          </div>
        </aside>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: `frontend/src/pages/GamePage.module.css`**

Порт панели прототипа (`.game-layout/.card/.turn/.thinking/.kv/.controls/.movelog`) + наш notice; компакт ≤900px — из прототипа:

```css
/* по prototype/index.html §GAME (panel/cards/thinking); notice — наш (доктрина рассинхрона) */
@value sumi, sumiSoft, vermillion, indigo, r, shadowSm, fontSerif, fontSans, bpCompact from "../styles/tokens.module.css";

.wrap { max-width: 1120px; margin: 0 auto; }
.loading { color: sumiSoft; padding: 40px; text-align: center; }
.eyebrow {
  font-family: fontSerif;
  font-weight: 600;
  letter-spacing: 5px;
  text-transform: uppercase;
  font-size: 11px;
  color: vermillion;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}
.eyebrow::before { content: ""; width: 26px; height: 1px; background: vermillion; display: inline-block; }
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 34px; align-items: start; }
.boardShell { display: flex; justify-content: center; min-width: 0; }
.boardShell > * { max-width: min(100%, calc(100dvh - 220px)); } /* квадрат к min-стороне вьюпорта (шапка+отступы ≈220px) */
.panel { display: flex; flex-direction: column; gap: 18px; }
.card {
  background: linear-gradient(#f6eedd, #efe4cd);
  border: 1px solid rgba(60, 45, 25, 0.14);
  border-radius: r;
  padding: 20px;
  box-shadow: shadowSm;
}
.card .eyebrow { margin-bottom: 10px; }
.turn { display: flex; align-items: center; gap: 14px; }
.who { font-family: fontSerif; font-weight: 700; font-size: 17px; }
.bigstone { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0; }
.bigBlack { background: radial-gradient(circle at 33% 28%, #56514b, #16130f); }
.bigWhite {
  background: radial-gradient(circle at 33% 28%, #fdfbf6, #cfc8b8);
  box-shadow: inset 0 0 0 1px rgba(120, 100, 70, 0.3);
}
.thinking { display: flex; align-items: center; gap: 9px; color: vermillion; font-size: 14px; margin-top: 12px; font-weight: 500; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: vermillion; animation: bnc 1s infinite ease-in-out; }
.dot:nth-child(2) { animation-delay: 0.15s; }
.dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes bnc {
  0%, 80%, 100% { transform: scale(0.5); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
.kv {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 9px 0;
  border-bottom: 1px dashed rgba(60, 45, 25, 0.16);
  font-size: 14px;
}
.kv:last-child { border-bottom: none; }
.k { color: sumiSoft; }
.v { font-weight: 500; }
.levelPill { font-family: fontSerif; font-weight: 700; color: indigo; }
.controls { display: flex; gap: 10px; }
.undoBtn {
  flex: 1;
  font-family: fontSans;
  font-weight: 500;
  font-size: 15px;
  letter-spacing: 0.5px;
  cursor: pointer;
  border-radius: 11px;
  padding: 12px;
  background: transparent;
  border: 1px solid rgba(60, 45, 25, 0.25);
  color: sumi;
  transition: 0.18s;
}
.undoBtn:hover:enabled { background: rgba(60, 45, 25, 0.06); }
.undoBtn:disabled { opacity: 0.45; cursor: default; }
.movelog {
  max-height: 150px;
  overflow: auto;
  font-size: 13px;
  color: sumiSoft;
  line-height: 1.9;
  font-variant-numeric: tabular-nums;
}
.movelog b { color: sumi; }
.notice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  background: rgba(189, 51, 38, 0.08);
  border: 1px dashed rgba(189, 51, 38, 0.35);
  border-radius: 11px;
  padding: 12px 14px;
  color: vermillion;
  font-size: 13.5px;
}
.noticeClose { background: none; border: none; cursor: pointer; color: vermillion; font-size: 16px; line-height: 1; }
.attr { font-size: 10px; letter-spacing: 0.4px; opacity: 0.45; text-align: right; }
.attr a { color: sumiSoft; text-decoration: none; }
.attr a:hover { opacity: 0.8; }
@media bpCompact {
  .layout { grid-template-columns: 1fr; }
}
```

- [ ] **Step 5: Зелёные и коммит**

Run: `npx vitest run src/pages/GamePage.test.tsx` → PASS. `npx tsc --noEmit` → чисто.

```bash
git add frontend/src/pages/GamePage.tsx frontend/src/pages/GamePage.module.css frontend/src/pages/GamePage.test.tsx
git commit -m "feat(rj-p82): GamePage — гобан + панель по прототипу (ход, уровень, undo, лог)"
```

---

### Task 10: Фронт — маршрут `/game/:gameId` и временная кнопка на главной

**Files:**
- Modify: `frontend/src/App.tsx` (lazy-маршрут в группе Shell)
- Modify: `frontend/src/pages/HomePage.tsx` + `frontend/src/pages/HomePage.module.css`
- Test: `frontend/src/pages/HomePage.test.tsx` (новый); дополнение `frontend/src/App.test.tsx`

- [ ] **Step 1: Failing-тесты**

`frontend/src/pages/HomePage.test.tsx`:

```tsx
import { it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import { FakeEventSource, installFakeEventSource } from "../test/eventsource";
import HomePage from "./HomePage";

beforeEach(() => {
  installFakeEventSource();
  FakeEventSource.reset();
});

it("кнопка «Новая партия (Новичок)» создаёт партию с novice и ведёт на /game/{id}", async () => {
  let body: unknown = null;
  server.use(
    http.post("/api/games", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ id: "g9" }); // HomePage берёт только id
    }),
  );
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/game/:gameId" element={<div>BOARD g9</div>} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole("button", { name: /новая партия/i }));
  expect(await screen.findByText("BOARD g9")).toBeInTheDocument();
  expect(body).toEqual({ opponent: { kind: "engine", levelId: "novice" } });
});

it("отказ создания: кнопка снова активна, на странице остаёмся", async () => {
  server.use(http.post("/api/games", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<HomePage />} />
      </Routes>
    </MemoryRouter>,
  );
  const btn = screen.getByRole("button", { name: /новая партия/i });
  await userEvent.click(btn);
  expect(await screen.findByRole("button", { name: /новая партия/i })).toBeEnabled();
  expect(screen.getByText("Доска ждёт")).toBeInTheDocument();
});
```

В `frontend/src/App.test.tsx` дописать тест маршрута (msw-хендлеры и фейк ES — внутри теста):

```tsx
import { FakeEventSource, installFakeEventSource } from "./test/eventsource";

it("маршрут /game/:id под защитой рендерит доску", async () => {
  installFakeEventSource();
  FakeEventSource.reset();
  resetUrl("/game/g1");
  server.use(
    meOk,
    http.get("/api/levels", () => HttpResponse.json([{ id: "novice", name: "Новичок" }])),
    http.get("/api/games/g1", () =>
      HttpResponse.json({
        id: "g1", owner_id: 1,
        controllers: { black: { kind: "user" }, white: { kind: "engine", levelId: "novice" } },
        your_color: "black", status: "awaiting_move",
        moves: [[7, 7]], undo_count: 0, cursor: 1, forbidden: [], winning_line: null,
      }),
    ),
  );
  render(<App />);
  expect(await screen.findByText(/ты играешь чёрными/)).toBeInTheDocument();
  expect(screen.getByText("alice")).toBeInTheDocument(); // внутри Shell
});
```

- [ ] **Step 2: Убедиться, что падают**

Run: `npx vitest run src/pages/HomePage.test.tsx src/App.test.tsx`
Expected: FAIL — кнопки нет; `/game/g1` уводит catch-all'ом на главную.

- [ ] **Step 3: Реализация**

`frontend/src/App.tsx` — добавить lazy-импорт и маршрут (рядом с HomePage):

```tsx
const GamePage = lazy(() => import("./pages/GamePage"));
// ...
<Route element={<Shell />}>
  <Route path="/" element={<HomePage />} />
  <Route path="/game/:gameId" element={<GamePage />} />
</Route>
```

`frontend/src/pages/HomePage.tsx` — целиком:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createGame } from "../game/api";
import styles from "./HomePage.module.css";

export default function HomePage() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  // Временная кнопка среза 2: хардкод novice. Заменяется экраном выбора уровня в срезе 3 (rj-as6).
  async function onNewGame() {
    if (busy) return;
    setBusy(true);
    try {
      const st = await createGame("novice");
      navigate(`/game/${st.id}`);
    } catch {
      setBusy(false); // осталась активной — можно повторить
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.eyebrow}>Твои партии</div>
      <h1 className={styles.title}>Доска ждёт</h1>
      <p className={styles.sub}>Здесь будет список партий (срез 3).</p>
      <button type="button" className={styles.newBtn} onClick={onNewGame} disabled={busy}>
        ＋ Новая партия (Новичок)
      </button>
    </div>
  );
}
```

`frontend/src/pages/HomePage.module.css` — дописать кнопку (стиль `.btn-vermillion` прототипа; в `@value`-импорт шапки добавить `vermillionDeep, shadowSm, fontSans` — `vermillion` там уже есть):

```css
.newBtn {
  margin-top: 22px;
  font-family: fontSans;
  font-weight: 500;
  font-size: 15px;
  letter-spacing: 0.5px;
  cursor: pointer;
  border: none;
  border-radius: 11px;
  padding: 14px 22px;
  background: vermillion;
  color: #fbeee6;
  box-shadow: shadowSm;
  transition: 0.18s;
}
.newBtn:hover:enabled { background: vermillionDeep; transform: translateY(-1px); }
.newBtn:disabled { opacity: 0.6; cursor: default; }
```

- [ ] **Step 4: Зелёные — весь фронт**

Run: `npx vitest run` → PASS (все файлы). `npx tsc --noEmit` → чисто. `npm run build` → сборка ок (lazy-chunk GamePage появился).

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/pages/HomePage.tsx frontend/src/pages/HomePage.module.css frontend/src/pages/HomePage.test.tsx
git commit -m "feat(rj-p82): маршрут /game/:id + временная кнопка новой партии (novice)"
```

---

### Task 11: Сопутствующие правки артефактов + финальные прогоны

**Files:**
- Modify: `docs/superpowers/specs/2026-06-07-renju-design.md` (§7, строка про Canvas/SVG)
- bd: описание эпика `rj-8wf`

- [ ] **Step 1: Мастер-спека §7**

В `docs/superpowers/specs/2026-06-07-renju-design.md` две правки (решение Alexey 2026-06-12, обоснование — спека среза 2):

Строку `- **Доска 15×15** на Canvas/SVG: сетка, камни, hover-превью, клик/тап.` заменить на:

```markdown
- **Доска 15×15** — DOM (абсолютно позиционированные элементы поверх фоновой
  сетки; решение 2026-06-12, спека среза 2): сетка, камни, hover-превью, клик/тап.
```

Во фрагменте «Доску рисуем на Canvas/SVG внутри компонента — React несёт обвязку…» заменить «на Canvas/SVG» на «DOM-слоями».

- [ ] **Step 2: Эпик rj-8wf**

Описание эпика перезаписывается целиком; единственное изменение против текущего —
фрагмент про Canvas-доску. Перед записью свериться с `bd show rj-8wf` (вдруг текст
менялся) и выполнить одной однострочной командой:

```bash
bd update rj-8wf --description="Спека §7. Доска DOM, экраны (логин/список/игра/настройки/админка/правила), SSE-клиент с reconnect, PWA. Включает фронт-часть дебюта: подсветка квадрата + блок ввода (зеркало opening_zone). Зависит от этапа 3. — СКВОЗНЫЕ ТРЕБОВАНИЯ (брейншторм 2026-06-12): (1) РЕСПОНСИВ — ОДИН desktop-лэйаут, fluid, держится до ~768px (iPad-портрет). iPad (ландшафт ~1024px+ и портрет ~768px) пользуется ДЕСКТОП-вью напрямую — отдельного планшетного дизайна НЕТ. Телефон ~375px — корнер-кейс, graceful-degrade (макс одна max-width-правка, не вылизываем). Реализация ТОЛЬКО CSS (media-queries + fluid grid/flex, единый DOM), DESKTOP-FIRST, БЕЗ JS-тернарников, БЕЗ mobile-first. Touch-friendly: tap-таргеты, ввод не зависит от hover (hover-превью доски — украшение). DOM-доска (решение 2026-06-12, спека среза 2): позиции в процентах, fluid без JS, доска к min-стороне вьюпорта. (2) ТЕСТЫ — вариант B: Vitest TDD на логику, RTL на поведение, Playwright e2e-смоук; visual-regression/геометрия ОТЛОЖЕНЫ, проверяем глазами+смоуком. Эпик нарезан: rj-0z2(1)->rj-p82(2)->rj-as6(3)->rj-xt2(4)/rj-h1p(5)->rj-ain(6) + PWA rj-puo + бэк-куски rj-dix/rj-8py."
```

- [ ] **Step 3: Полные прогоны**

- Бэк (из `backend/`): `uv run pytest -q` (последовательно) → зелёные; `uv run ruff check app tests scripts` → чисто.
- Фронт (из `frontend/`): `npx vitest run` → зелёные; `npx tsc --noEmit` → чисто; `npm run build` → ок.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-06-07-renju-design.md .beads
git commit -m "docs(rj-p82): мастер-спека §7 и эпик rj-8wf — DOM-доска вместо Canvas/SVG"
```

---

## После плана (вне задач, по workflow)

- Ручная приёмка Alexey: собрать `dist/` (`npm run build`), живая партия против novice через бэк (uvicorn уже крутится на :8000), скриншоты доски/зоны/финиша. На приёмке утверждаются: вид рамки зоны, направление нумерации лога, вид метки выигрышной линии.
- Холистик-ревью всей ветки (свежий ревьюер) → фиксы → мерж по явной команде.
