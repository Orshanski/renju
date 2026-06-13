import { it, expect } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { getGamesSummary, favoriteGame, unfavoriteGame, deleteGame } from "./api";

const SUMMARY = [
  { id: "g1", status: "awaiting_move", section: "current", level_id: "novice",
    your_color: "black", move_count: 3, favorite: false, updated_at: "2026-06-13T10:00:00", finished_at: null },
];

it("getGamesSummary дёргает /api/games/summary с section и возвращает массив", async () => {
  let url = "";
  server.use(http.get("/api/games/summary", ({ request }) => {
    url = new URL(request.url).search;
    return HttpResponse.json(SUMMARY);
  }));
  const out = await getGamesSummary("finished");
  expect(url).toBe("?section=finished");
  expect(out).toEqual(SUMMARY);
});

it("favoriteGame POST'ит /favorite и возвращает true", async () => {
  server.use(http.post("/api/games/g1/favorite", () => HttpResponse.json(true)));
  expect(await favoriteGame("g1")).toBe(true);
});

it("unfavoriteGame POST'ит /unfavorite", async () => {
  let hit = false;
  server.use(http.post("/api/games/g1/unfavorite", () => { hit = true; return HttpResponse.json(true); }));
  await unfavoriteGame("g1");
  expect(hit).toBe(true);
});

it("deleteGame DELETE'ит партию и переваривает 204", async () => {
  server.use(http.delete("/api/games/g1", () => new HttpResponse(null, { status: 204 })));
  await expect(deleteGame("g1")).resolves.toBeUndefined();
});
