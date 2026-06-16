import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, http, HttpResponse } from "../test/msw";
import { EngineTab } from "./EngineTab";

const CFG = { levels: [{ id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000 }], nnue: true };

it("показывает уровни, время в секундах; правка+сохранить шлёт мс", async () => {
  let body: unknown = null;
  server.use(
    http.get("/api/admin/engine-config", () => HttpResponse.json(CFG)),
    http.put("/api/admin/engine-config", async ({ request }) => { body = await request.json(); return HttpResponse.json(CFG); }),
  );
  render(<EngineTab />);
  const strength = await screen.findByLabelText(/Новичок.*сила/i);
  await userEvent.clear(strength);
  await userEvent.type(strength, "9");
  await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  expect((body as { levels: { id: string; strength: number; timeout_ms: number }[]; nnue: boolean }).levels[0]).toEqual({ id: "novice", strength: 9, timeout_ms: 1000 }); // секунды 1.0 → 1000 мс
  expect((body as { nnue: boolean }).nnue).toBe(true);
});

it("отказ загрузки → ошибка", async () => {
  server.use(http.get("/api/admin/engine-config", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  render(<EngineTab />);
  expect(await screen.findByText(/не удалось загрузить/i)).toBeInTheDocument();
});
