import { it, expect } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { getEngineConfig, putEngineConfig } from "./admin.api";

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
  const updated = await putEngineConfig({ levels: [{ id: "novice", strength: 9, timeout_ms: 2000 }], nnue: false });
  expect(body).toEqual({ levels: [{ id: "novice", strength: 9, timeout_ms: 2000 }], nnue: false });
  expect(updated.levels[0].strength).toBe(9);
  expect(updated.nnue).toBe(false);
});
