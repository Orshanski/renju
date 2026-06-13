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
