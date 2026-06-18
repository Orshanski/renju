import { it, expect } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { getEngineConfig, putEngineConfig, listUsers, createUser, updateUser, deleteUser } from "./admin.api";

it("getEngineConfig парсит уровни и nnue", async () => {
  server.use(http.get("/api/admin/engine-config", () => HttpResponse.json({
    levels: [{ id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000 }],
    nnue: true,
  })));
  const cfg = await getEngineConfig();
  expect(cfg.nnue).toBe(true);
  expect(cfg.levels[0]).toEqual({ id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000 });
});

it("putEngineConfig шлёт тело и возвращает обновлённое", async () => {
  let body: unknown = null;
  server.use(http.put("/api/admin/engine-config", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json({ levels: [{ id: "novice", name: "Новичок", strength: 9, timeout_ms: 2000 }], nnue: false });
  }));
  const updated = await putEngineConfig({ levels: [{ id: "novice", strength: 9, timeout_ms: 2000, max_depth: 5 }], nnue: false });
  expect(body).toEqual({ levels: [{ id: "novice", strength: 9, timeout_ms: 2000, max_depth: 5 }], nnue: false });
  expect(updated.levels[0].strength).toBe(9);
  expect(updated.nnue).toBe(false);
});

it("listUsers возвращает массив UserAdminDTO", async () => {
  server.use(http.get("/api/admin/users", () => HttpResponse.json([
    { id: 1, username: "alice", role: "admin", created_at: "2026-06-17T10:00:00" },
    { id: 2, username: "bob", role: "user", created_at: "2026-06-15T08:30:00" },
  ])));
  const users = await listUsers();
  expect(users).toHaveLength(2);
  expect(users[0]).toEqual({ id: 1, username: "alice", role: "admin", created_at: "2026-06-17T10:00:00" });
  expect(users[1].role).toBe("user");
});

it("createUser шлёт тело и возвращает id", async () => {
  let body: unknown = null;
  server.use(http.post("/api/admin/users", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json({ id: 42 });
  }));
  const result = await createUser({ username: "charlie", password: "secret", role: "user" });
  expect(body).toEqual({ username: "charlie", password: "secret", role: "user" });
  expect(result).toEqual({ id: 42 });
});

it("updateUser шлёт PUT с телом и возвращает ok", async () => {
  let body: unknown = null;
  server.use(http.put("/api/admin/users/5", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json({ ok: true });
  }));
  const result = await updateUser(5, { role: "admin" });
  expect(body).toEqual({ role: "admin" });
  expect(result).toEqual({ ok: true });
});

it("deleteUser шлёт DELETE и возвращает ok", async () => {
  server.use(http.delete("/api/admin/users/3", () => HttpResponse.json({ ok: true })));
  const result = await deleteUser(3);
  expect(result).toEqual({ ok: true });
});
