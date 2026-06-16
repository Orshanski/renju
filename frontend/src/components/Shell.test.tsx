import { it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import { AuthProvider } from "../auth/AuthContext";
import { Shell } from "./Shell";

function tree(initialEntries: string[] = ["/"]) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/login" element={<div>LOGIN</div>} />
          <Route element={<Shell />}>
            <Route path="/" element={<div>HOME</div>} />
            <Route path="/settings" element={<div>SETTINGS</div>} />
            <Route path="/admin" element={<div>ADMIN</div>} />
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

it("навбар показывает вкладки «Партии» и «Настройки»", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "alice", role: "user" })));
  tree();
  await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Партии" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Настройки" })).toBeInTheDocument();
});

it("вкладка «Админ» видна при role=admin", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "bob", role: "admin" })));
  tree();
  await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Админ" })).toBeInTheDocument();
});

it("вкладка «Админ» НЕ видна при role=user", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "alice", role: "user" })));
  tree();
  await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "Админ" })).not.toBeInTheDocument();
});

it("активная вкладка «Партии» при роуте /", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "alice", role: "user" })));
  tree(["/"]);
  await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Партии" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "Настройки" })).not.toHaveAttribute("aria-current", "page");
});

it("активная вкладка «Админ» при роуте /admin (admin-user)", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "bob", role: "admin" })));
  tree(["/admin"]);
  await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Админ" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "Партии" })).not.toHaveAttribute("aria-current", "page");
});
