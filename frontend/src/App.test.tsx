import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { server, http, HttpResponse } from "./test/msw";
import { apiRequest, ApiError } from "./api/client";
import { FakeEventSource, installFakeEventSource } from "./test/eventsource";
import App from "./App";

// Поведенческие тесты App-сборки целиком (jsdom): бридж 401→navigate, catch-all, ленивые экраны.
// BrowserRouter работает на window.history — перед каждым тестом возвращаем URL на корень.
function resetUrl(path = "/") {
  window.history.replaceState(null, "", path);
}

const meOk = http.get("/api/auth/me", () =>
  HttpResponse.json({ id: 1, username: "alice", role: "user" }),
);

it("без сессии → ленивый экран логина (me=401 по умолчанию из msw)", async () => {
  resetUrl("/");
  render(<App />);
  expect(await screen.findByRole("button", { name: /войти/i })).toBeInTheDocument();
});

it("глобальный 401 после входа → бридж уводит на /login", async () => {
  resetUrl("/");
  server.use(meOk, http.get("/api/expired", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
  render(<App />);
  await screen.findByText("alice"); // вошли, каркас отрисован
  // имитация «сессия протухла» на произвольном вызове API
  await expect(apiRequest("GET", "/api/expired")).rejects.toBeInstanceOf(ApiError);
  expect(await screen.findByRole("button", { name: /войти/i })).toBeInTheDocument();
});

it("неизвестный путь → catch-all * на главную", async () => {
  resetUrl("/nope/nowhere");
  server.use(meOk);
  render(<App />);
  expect(await screen.findByText("Доска ждёт")).toBeInTheDocument(); // HomePage
  expect(window.location.pathname).toBe("/");
});

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
