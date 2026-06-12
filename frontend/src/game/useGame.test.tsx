import { renderHook, act, waitFor } from "@testing-library/react";
import { it, expect, beforeEach, vi } from "vitest";
import { server, http, HttpResponse } from "../test/msw";
import { FakeEventSource, installFakeEventSource } from "../test/eventsource";
import { setUnauthorizedHandler } from "../api/client";
import { useGame } from "./useGame";
import type { GameStateDTO } from "./types";

const state = (over: Partial<GameStateDTO> = {}): GameStateDTO => ({
  id: "g1", owner_id: 1,
  controllers: { black: { kind: "user" }, white: { kind: "engine", levelId: "novice" } },
  your_color: "black", status: "awaiting_move",
  moves: [[7, 7], [6, 6]], undo_count: 0, cursor: 5, forbidden: [], winning_line: null,
  ...over,
});
const meOk = http.get("/api/auth/me", () => HttpResponse.json({ id: 1, username: "a", role: "user" }));

beforeEach(() => {
  installFakeEventSource();
  FakeEventSource.reset();
});

it("старт: GET → view; EventSource открыт со since = state.cursor из GET-ответа", async () => {
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view?.moves).toHaveLength(2));
  expect(FakeEventSource.last().url).toBe("/api/games/g1/events?since=5");
});

it("SSE move соперника дорисовывается", async () => {
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  act(() => FakeEventSource.last().emit("move", { seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 2 } }));
  expect(result.current.view?.moves).toHaveLength(3);
});

it("оптимистичный ход: камень встаёт до ответа сервера; событие снимает pending раньше 202", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  server.use(
    http.get("/api/games/g1", () => HttpResponse.json(state())),
    http.post("/api/games/g1/move", async () => {
      await gate; // 202 задерживаем — своё move-событие придёт раньше (штатная гонка, спека M1)
      return HttpResponse.json({ accepted: true }, { status: 202 });
    }),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  let done!: Promise<void>;
  act(() => { done = result.current.play(8, 7); }); // ход №2 — зона 5×5, (8,7) легален
  await waitFor(() => expect(result.current.view?.pendingIndex).toBe(2)); // камень встал, POST ещё висит
  act(() => FakeEventSource.last().emit("move", { seq: 6, type: "move", payload: { by: "black", point: [8, 7], move_index: 2 } }));
  expect(result.current.view?.pendingIndex).toBeNull(); // подтверждён событием ДО 202
  release();
  await act(async () => { await done; });
  expect(result.current.notice).toBeNull(); // исход POST после подтверждения — игнор
  expect(result.current.view?.moves).toHaveLength(3);
});

it("разрыв SSE при живом 202: pending переживает reconnect и снимается реплеем", async () => {
  server.use(
    meOk,
    http.get("/api/games/g1", () => HttpResponse.json(state())),
    http.post("/api/games/g1/move", () => HttpResponse.json({ accepted: true }, { status: 202 })),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  await act(async () => { await result.current.play(8, 7); }); // 202 пришёл, своё событие — нет
  expect(result.current.view?.pendingIndex).toBe(2);
  act(() => FakeEventSource.last().fail());
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2)); // reconnect с cursor=5
  act(() => FakeEventSource.last().emit("move", { seq: 6, type: "move", payload: { by: "black", point: [8, 7], move_index: 2 } })); // реплей с буфера
  expect(result.current.view?.pendingIndex).toBeNull();
  expect(result.current.view?.moves).toHaveLength(3);
});

it("отказ POST до подтверждения: откат, ресинхрон, нейтральное сообщение", async () => {
  let gets = 0;
  server.use(
    http.get("/api/games/g1", () => {
      gets += 1;
      return HttpResponse.json(state()); // ресинхрон вернёт исходные 2 камня
    }),
    http.post("/api/games/g1/move", () => HttpResponse.json({ detail: "opponent_thinking" }, { status: 409 })),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  await act(async () => { await result.current.play(8, 7); });
  expect(result.current.view?.moves).toHaveLength(2); // откатился
  expect(result.current.view?.pendingIndex).toBeNull();
  expect(result.current.notice).toBe("Доска обновлена — ход не прошёл");
  expect(gets).toBe(2); // стартовый + ресинхрон
});

it("нелегальный клик не ходит (POST нет)", async () => {
  let posts = 0;
  server.use(
    http.get("/api/games/g1", () => HttpResponse.json(state())),
    http.post("/api/games/g1/move", () => {
      posts += 1;
      return HttpResponse.json({ accepted: true }, { status: 202 });
    }),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  await act(async () => { await result.current.play(7, 7); }); // занято
  await act(async () => { await result.current.play(1, 1); }); // вне зоны 5×5
  expect(posts).toBe(0);
  expect(result.current.view?.moves).toHaveLength(2);
});

it("undo: ответ-state заменяет вью целиком", async () => {
  server.use(
    http.get("/api/games/g1", () => HttpResponse.json(state({ moves: [[7, 7], [6, 6], [8, 7], [0, 0]], cursor: 9 }))),
    http.post("/api/games/g1/undo", () => HttpResponse.json(state({ moves: [[7, 7], [6, 6]], cursor: 11 }))),
  );
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view?.moves).toHaveLength(4));
  await act(async () => { await result.current.undoMove(); });
  expect(result.current.view?.moves).toHaveLength(2);
  expect(result.current.view?.cursor).toBe(11);
});

it("пропуск seq → ресинхрон через GET", async () => {
  let gets = 0;
  server.use(http.get("/api/games/g1", () => {
    gets += 1;
    return HttpResponse.json(state({ cursor: gets === 1 ? 5 : 9 }));
  }));
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  await act(async () => {
    FakeEventSource.last().emit("forbidden", { seq: 9, type: "forbidden", payload: { points: [] } }); // 5 → 9: дыра
    await Promise.resolve();
  });
  await waitFor(() => expect(result.current.view?.cursor).toBe(9));
  expect(gets).toBe(2);
});

it("разрыв SSE: пауза → проверка сессии → новый EventSource с текущим курсором", async () => {
  server.use(meOk, http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result } = renderHook(() => useGame("g1", 0)); // reconnectDelayMs=0 — без таймеров
  await waitFor(() => expect(result.current.view).not.toBeNull());
  const first = FakeEventSource.last();
  act(() => {
    first.emit("move", { seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 2 } });
    first.fail();
  });
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
  expect(first.readyState).toBe(2); // старый закрыт
  expect(FakeEventSource.last().url).toBe("/api/games/g1/events?since=6"); // курсор актуальный
});

it("сессия отозвана: 401 на проверке → глобальный обработчик, реконнекта нет", async () => {
  const onUnauthorized = vi.fn();
  setUnauthorizedHandler(onUnauthorized);
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  // дефолтный msw-хендлер /api/auth/me — 401
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  act(() => FakeEventSource.last().fail());
  await waitFor(() => expect(onUnauthorized).toHaveBeenCalled());
  expect(FakeEventSource.instances).toHaveLength(1); // новый стрим не открыт
});

it("error-событие → ненавязчивое сообщение, состояние цело", async () => {
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  act(() => FakeEventSource.last().emit("error", { seq: 6, type: "error", payload: { message: "engine died" } }));
  expect(result.current.notice).toBe("Движок споткнулся — партия продолжится автоматически");
  expect(result.current.view?.moves).toHaveLength(2);
});

it("размонтирование закрывает стрим", async () => {
  server.use(http.get("/api/games/g1", () => HttpResponse.json(state())));
  const { result, unmount } = renderHook(() => useGame("g1", 0));
  await waitFor(() => expect(result.current.view).not.toBeNull());
  unmount();
  expect(FakeEventSource.last().readyState).toBe(2);
});
