import { it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { server, http, HttpResponse } from "../test/msw";
import { AuthProvider } from "../auth/AuthContext";
import LoginPage from "./LoginPage";

function tree() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>HOME</div>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}
const me401 = http.get("/api/auth/me", () => HttpResponse.json({ detail: "x" }, { status: 401 }));

it("успешный вход → переход на /", async () => {
  server.use(me401, http.post("/api/auth/login", () =>
    HttpResponse.json({ ok: true, user: { id: 1, username: "alice", role: "user" } })));
  tree();
  await userEvent.type(screen.getByLabelText(/имя/i), "alice");
  await userEvent.type(screen.getByLabelText(/пароль/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /войти/i }));
  await waitFor(() => expect(screen.getByText("HOME")).toBeInTheDocument());
});

it("401 → inline «неверные имя или пароль», пароль очищен, без редиректа", async () => {
  server.use(me401, http.post("/api/auth/login", () => HttpResponse.json({ detail: "Invalid" }, { status: 401 })));
  tree();
  await userEvent.type(screen.getByLabelText(/имя/i), "alice");
  await userEvent.type(screen.getByLabelText(/пароль/i), "bad");
  await userEvent.click(screen.getByRole("button", { name: /войти/i }));
  await waitFor(() => expect(screen.getByText(/неверные имя или пароль/i)).toBeInTheDocument());
  expect(screen.getByLabelText(/пароль/i)).toHaveValue("");
  expect(screen.queryByText("HOME")).not.toBeInTheDocument();
});

it("429 → «слишком много попыток»", async () => {
  server.use(me401, http.post("/api/auth/login", () => HttpResponse.json({ detail: "Too many" }, { status: 429 })));
  tree();
  await userEvent.type(screen.getByLabelText(/имя/i), "alice");
  await userEvent.type(screen.getByLabelText(/пароль/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /войти/i }));
  await waitFor(() => expect(screen.getByText(/слишком много попыток/i)).toBeInTheDocument());
});

it("500/прочее → общий «ошибка входа», без редиректа", async () => {
  server.use(me401, http.post("/api/auth/login", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  tree();
  await userEvent.type(screen.getByLabelText(/имя/i), "alice");
  await userEvent.type(screen.getByLabelText(/пароль/i), "pw");
  await userEvent.click(screen.getByRole("button", { name: /войти/i }));
  await waitFor(() => expect(screen.getByText(/ошибка входа/i)).toBeInTheDocument());
  expect(screen.queryByText("HOME")).not.toBeInTheDocument();
});
