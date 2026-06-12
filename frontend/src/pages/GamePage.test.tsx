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
