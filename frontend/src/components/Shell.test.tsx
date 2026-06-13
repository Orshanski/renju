import { it, expect } from "vitest";
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

it("клик по бренду → переход на главный экран (выход из партии)", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "alice", role: "user" })));
  render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/game/g1"]}>
        <Routes>
          <Route element={<Shell />}>
            <Route path="/" element={<div>HOME</div>} />
            <Route path="/game/:id" element={<div>GAME</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
  await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());
  expect(screen.getByText("GAME")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /連珠|renju/i }));
  await waitFor(() => expect(screen.getByText("HOME")).toBeInTheDocument());
});

it("клик «выйти» → logout → редирект на /login", async () => {
  server.use(
    http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "alice", role: "user" })),
    http.post("/api/auth/logout", () => HttpResponse.json({ ok: true })),
  );
  tree();
  await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());
  await userEvent.click(screen.getByRole("button", { name: /выйти/i })); // текст кнопки — по прототипу
  await waitFor(() => expect(screen.getByText("LOGIN")).toBeInTheDocument());
});
