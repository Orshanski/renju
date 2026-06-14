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

it("отказ создания партии: кнопка снова активна, остаёмся на экране", async () => {
  server.use(
    http.get("/api/levels", () => HttpResponse.json([{ id: "novice", name: "Новичок" }])),
    http.post("/api/games", () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
  );
  render(
    <MemoryRouter initialEntries={["/new"]}>
      <Routes><Route path="/new" element={<NewGamePage />} /></Routes>
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole("button", { name: /Новичок/ }));
  expect(await screen.findByRole("button", { name: /Новичок/ })).toBeEnabled();
  expect(screen.getByText("Выбери уровень")).toBeInTheDocument();
});
