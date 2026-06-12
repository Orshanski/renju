import { it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, http, HttpResponse } from "../test/msw";
import { AuthProvider, useAuth } from "./AuthContext";

function Probe() {
  const { user, loading, login, logout } = useAuth();
  if (loading) return <div>loading</div>;
  return (
    <div>
      <span>user:{user ? user.username : "none"}</span>
      <button onClick={() => login("alice", "pw")}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

const me = (u: object | null, status = 200) =>
  http.get("/api/auth/me", () => HttpResponse.json(u as object, { status }));

it("на старте me=200 → user установлен", async () => {
  server.use(me({ id: 1, username: "alice", role: "admin" }));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("user:alice")).toBeInTheDocument());
});

it("на старте me=401 → user=none, без ошибки", async () => {
  server.use(me({ detail: "x" }, 401));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("user:none")).toBeInTheDocument());
});

it("на старте me=500 → user=none, без падения (не-401 → console.error)", async () => {
  const spy = vi.spyOn(console, "error").mockImplementation(() => {});
  server.use(me({ detail: "boom" }, 500));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("user:none")).toBeInTheDocument());
  expect(spy).toHaveBeenCalled(); // не-401 логируется, но юзер всё равно null
  spy.mockRestore();
});

it("login разворачивает .user; logout чистит", async () => {
  server.use(
    me({ detail: "x" }, 401),
    http.post("/api/auth/login", () => HttpResponse.json({ ok: true, user: { id: 2, username: "bob", role: "user" } })),
    http.post("/api/auth/logout", () => HttpResponse.json({ ok: true })),
  );
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("user:none")).toBeInTheDocument());
  await userEvent.click(screen.getByText("login"));
  await waitFor(() => expect(screen.getByText("user:bob")).toBeInTheDocument());
  await userEvent.click(screen.getByText("logout"));
  await waitFor(() => expect(screen.getByText("user:none")).toBeInTheDocument());
});

it("useAuth вне AuthProvider → бросает понятную ошибку", () => {
  function Bare() {
    useAuth();
    return null;
  }
  const spy = vi.spyOn(console, "error").mockImplementation(() => {}); // подавить лог React об ошибке рендера
  expect(() => render(<Bare />)).toThrow(/within AuthProvider/);
  spy.mockRestore();
});
