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

it("ошибка загрузки раздела показывает заглушку, а не вечную загрузку", async () => {
  server.use(http.get("/api/games/summary", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  render(<MemoryRouter><Routes><Route path="*" element={<HomePage />} /></Routes></MemoryRouter>);
  expect(await screen.findByText(/Здесь пусто/)).toBeInTheDocument();
});
