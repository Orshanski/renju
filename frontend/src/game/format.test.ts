import { it, expect } from "vitest";
import { statusLabel, statusTone, sectionDateLabel } from "./format";

it("statusLabel: текущая — по твоему ходу; завершённая — по результату", () => {
  expect(statusLabel("awaiting_move", "black")).toBe("Твой ход");
  expect(statusLabel("opponent_thinking", "black")).toBe("Ход соперника");
  expect(statusLabel("finished_black", "black")).toBe("Победа");
  expect(statusLabel("finished_white", "black")).toBe("Поражение");
  expect(statusLabel("finished_white", "white")).toBe("Победа");
  expect(statusLabel("finished_black", "white")).toBe("Поражение");
  expect(statusLabel("finished_black", null)).toBe("Завершено");
  expect(statusLabel("finished_draw", "black")).toBe("Ничья");
});

it("statusTone: твой ход→think, соперник→go, любая завершённая→done", () => {
  expect(statusTone("awaiting_move")).toBe("think");
  expect(statusTone("opponent_thinking")).toBe("go");
  expect(statusTone("finished_black")).toBe("done");
  expect(statusTone("finished_white")).toBe("done");
  expect(statusTone("finished_draw")).toBe("done");
});

it("sectionDateLabel: текущая — обновлено(updated_at); завершённая/избранная — завершено(finished_at)", () => {
  const s = { updated_at: "2026-06-13T10:00:00", finished_at: "2026-06-12T09:00:00" };
  expect(sectionDateLabel("current", s)).toMatch(/^Обновлено /);
  expect(sectionDateLabel("finished", s)).toMatch(/^Завершено /);
  expect(sectionDateLabel("favorite", s)).toMatch(/^Завершено /);
  expect(sectionDateLabel("current", { updated_at: null, finished_at: null })).toBe("");
  expect(sectionDateLabel("finished", { updated_at: null, finished_at: null })).toBe("");
});

it("sectionDateLabel: naive-UTC время (без Z) трактуется как UTC, не локально", () => {
  // бэк отдаёт время без пояса; метка не должна зависеть от того, дописан ли 'Z'
  const naive = { updated_at: "2026-06-13T10:00:00", finished_at: null };
  const withZ = { updated_at: "2026-06-13T10:00:00Z", finished_at: null };
  expect(sectionDateLabel("current", naive)).toBe(sectionDateLabel("current", withZ));
});
