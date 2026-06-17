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
const settings = http.get("/api/settings", () =>
  HttpResponse.json({ games_limit: 10, games_limit_enabled: false, undo_enabled: true, undo_limit: null, undo_after_game_end: true }),
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
  server.use(settings); // дефолтная политика undo: enabled, без лимита
});

it("панель: заголовок, чей ход, уровень по имени, цвет, № хода, лог", async () => {
  server.use(levels, http.get("/api/games/g1", () => HttpResponse.json(state())));
  renderPage();
  expect(await screen.findByText(/ты играешь чёрными/)).toBeInTheDocument();
  expect(screen.getByText("Ход соперника")).toBeInTheDocument(); // 3 камня → ход белых, мы чёрные
  expect(await screen.findByText("Новичок")).toBeInTheDocument();
  expect(screen.getByText("№3")).toBeInTheDocument();
  expect(screen.getByText("подсвечены ✕")).toBeInTheDocument();
  const log = screen.getByTestId("movelog");
  expect(log.textContent).toContain("3. ⚫ I8"); // новые сверху: I8 = (8,7)
  expect(log.firstChild?.textContent).toContain("3.");
});

it("«← К партиям» уводит на главный экран", async () => {
  server.use(levels, http.get("/api/games/g1", () => HttpResponse.json(state())));
  render(
    <MemoryRouter initialEntries={["/game/g1"]}>
      <Routes>
        <Route path="/game/:gameId" element={<GamePage />} />
        <Route path="/" element={<div>СПИСОК</div>} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByText(/ты играешь/);
  await userEvent.click(screen.getByRole("button", { name: /к партиям/i }));
  expect(await screen.findByText("СПИСОК")).toBeInTheDocument();
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
  // ждём резолва настроек (кнопка disabled пока политика не загружена)
  await waitFor(() => expect(screen.getByRole("button", { name: /отменить/i })).not.toBeDisabled());
  await userEvent.click(screen.getByRole("button", { name: /отменить/i }));
  await waitFor(() => expect(screen.queryByTestId("win-9-7")).not.toBeInTheDocument());
  expect(screen.getByText("Твой ход")).toBeInTheDocument();
});

it("undo задизейблен на завершённой партии, когда откат после конца выключен в настройках", async () => {
  // сценарий: партия выиграна, камней достаточно для отката, но игрок выключил
  // «откат после конца партии» → кнопка блокируется (не клик→422→невнятный алерт)
  const finished = state({
    status: "finished_black",
    moves: [[7, 7], [6, 6], [8, 7], [0, 0], [9, 7], [0, 1], [10, 7], [0, 2], [11, 7]],
    winning_line: [[7, 7], [8, 7], [9, 7], [10, 7], [11, 7]],
    cursor: 20,
  });
  server.use(
    levels,
    http.get("/api/settings", () =>
      HttpResponse.json({
        games_limit: 10,
        games_limit_enabled: false,
        undo_enabled: true,
        undo_limit: null,
        undo_after_game_end: false, // ← откат после конца выключен
      }),
    ),
    http.get("/api/games/g1", () => HttpResponse.json(finished)),
  );
  renderPage();
  await screen.findByText("Победа чёрных ⚫");
  // в близнеце-тесте (after_game_end=true) кнопка после резолва настроек включается;
  // здесь — политика запрещает, поэтому даже после резолва остаётся disabled
  await new Promise((r) => setTimeout(r, 0)); // flush резолва getSettings
  expect(screen.getByRole("button", { name: /отменить/i })).toBeDisabled();
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
  await userEvent.click(screen.getByRole("button", { name: /закрыть/i }));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("до резолва GET — «Загрузка…»", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  server.use(levels, http.get("/api/games/g1", async () => {
    await gate;
    return HttpResponse.json(state());
  }));
  renderPage();
  expect(screen.getByText("Загрузка…")).toBeInTheDocument();
  release();
  expect(await screen.findByText(/ты играешь/)).toBeInTheDocument();
});

it("партия не найдена (404) → «Не удалось загрузить партию»", async () => {
  server.use(levels, http.get("/api/games/g1", () => HttpResponse.json({ detail: "nf" }, { status: 404 })));
  renderPage();
  expect(await screen.findByText("Не удалось загрузить партию")).toBeInTheDocument();
});

it("живая SSE-серия: ход движка + финальный status подсвечивают линию на экране", async () => {
  // старт: 8 камней, ход чёрных (наш), у чёрных горизонталь 7..10 на y=7
  const running = state({
    moves: [[7, 7], [6, 6], [8, 7], [0, 0], [9, 7], [0, 1], [10, 7], [0, 2]],
    cursor: 17,
  });
  server.use(
    levels,
    http.get("/api/games/g1", () => HttpResponse.json(running)),
    http.post("/api/games/g1/move", () => HttpResponse.json({ accepted: true }, { status: 202 })),
  );
  renderPage();
  await screen.findByText("Твой ход");
  await userEvent.click(screen.getByRole("button", { name: "L8" })); // (11,7) замыкает пятёрку
  act(() => {
    FakeEventSource.last().emit("move", { seq: 18, type: "move", payload: { by: "black", point: [11, 7], move_index: 8 } });
    FakeEventSource.last().emit("status", { seq: 19, type: "status", payload: { status: "finished_black", winning_line: [[7, 7], [8, 7], [9, 7], [10, 7], [11, 7]] } });
  });
  expect(await screen.findByText("Победа чёрных ⚫")).toBeInTheDocument();
  expect(screen.getByTestId("win-11-7")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "A1" })).toBeDisabled();
});
