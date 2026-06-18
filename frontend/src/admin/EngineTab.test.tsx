import { it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, http, HttpResponse } from "../test/msw";
import { EngineTab } from "./EngineTab";

const CFG = { levels: [{ id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000, max_depth: 4, depth_ceiling: 4 }], nnue: true };

it("показывает уровни, время в секундах; правка+сохранить шлёт мс", async () => {
  let body: unknown = null;
  server.use(
    http.get("/api/admin/engine-config", () => HttpResponse.json(CFG)),
    http.put("/api/admin/engine-config", async ({ request }) => { body = await request.json(); return HttpResponse.json(CFG); }),
  );
  render(<EngineTab />);
  const strength = await screen.findByLabelText(/Новичок.*сила/i);
  fireEvent.change(strength, { target: { value: "9" } });
  await userEvent.click(screen.getByRole("button", { name: "Сохранить" }));
  expect((body as { levels: { id: string; strength: number; timeout_ms: number; max_depth: number }[]; nnue: boolean }).levels[0]).toEqual({ id: "novice", strength: 9, timeout_ms: 1000, max_depth: 4 }); // depth 4 ≤ потолок depthCeiling(9)=5 → не режется; секунды 1.0 → 1000 мс
  expect((body as { nnue: boolean }).nnue).toBe(true);
});

it("отказ загрузки → ошибка", async () => {
  server.use(http.get("/api/admin/engine-config", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  render(<EngineTab />);
  expect(await screen.findByText(/не удалось загрузить/i)).toBeInTheDocument();
});

it("при падении потолка глубина встаёт на верхнюю границу", async () => {
  const cfg = { levels: [
    { id: "novice", name: "Новичок", strength: 5, timeout_ms: 1000, max_depth: 4, depth_ceiling: 4 },
    { id: "easy", name: "Лёгкий", strength: 15, timeout_ms: 1500, max_depth: 6, depth_ceiling: 6 },
  ], nnue: true };
  server.use(http.get("/api/admin/engine-config", () => HttpResponse.json(cfg)));
  render(<EngineTab />);
  const easyDepth = await screen.findByLabelText("Лёгкий глубина");
  expect(easyDepth).toHaveValue(6);
  const easyStrength = screen.getByLabelText(/Лёгкий.*сила/i);
  fireEvent.change(easyStrength, { target: { value: "7" } });
  expect(easyDepth).toHaveValue(5); // depthCeiling(7)=5 → depth 6 встаёт на 5
});
