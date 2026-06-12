import { it, expect, describe } from "vitest";
import { applyEvent, fromState, placePending } from "./reducer";
import type { GameView } from "./view";
import type { GameEventMessage, GameStateDTO } from "./types";

const dto: GameStateDTO = {
  id: "g1", owner_id: 1,
  controllers: { black: { kind: "user" }, white: { kind: "engine", levelId: "novice" } },
  your_color: "black", status: "awaiting_move",
  moves: [[7, 7], [6, 6]], undo_count: 0, cursor: 5, forbidden: [[5, 5]], winning_line: null,
};
const view = (): GameView => fromState(dto);
const ev = (e: GameEventMessage) => e;

describe("fromState", () => {
  it("snake_case → вью-модель; levelId движка извлечён", () => {
    const v = view();
    expect(v).toMatchObject({
      id: "g1", yourColor: "black", status: "awaiting_move", cursor: 5,
      pendingIndex: null, winningLine: null, opponentLevelId: "novice",
    });
    expect(v.moves).toEqual([[7, 7], [6, 6]]);
    expect(v.forbidden).toEqual([[5, 5]]);
  });
});

describe("правило курсора", () => {
  it("seq ≤ cursor — дубль реплея, игнор (state не меняется)", () => {
    const v = view();
    const r = applyEvent(v, ev({ seq: 5, type: "forbidden", payload: { points: [[1, 1]] } }));
    expect(r).toBe(v);
  });
  it("seq == cursor+1 — применить, cursor сдвинут", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "forbidden", payload: { points: [[1, 1]] } }));
    expect(r).not.toBe("resync");
    expect((r as GameView).cursor).toBe(6);
    expect((r as GameView).forbidden).toEqual([[1, 1]]);
  });
  it("seq > cursor+1 — пропуск событий → resync", () => {
    expect(applyEvent(view(), ev({ seq: 8, type: "forbidden", payload: { points: [] } }))).toBe("resync");
  });
});

describe("move", () => {
  it("чужой ход: move_index == moves.length → дорисовать, forbidden обнулён", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 2 } })) as GameView;
    expect(r.moves).toEqual([[7, 7], [6, 6], [8, 8]]);
    expect(r.forbidden).toEqual([]); // позиция сменилась; актуальный набор придёт forbidden-событием
  });
  it("своё подтверждение: совпали точка и АБСОЛЮТНЫЙ индекс pending → pending снят, камень остаётся", () => {
    const pending = placePending(view(), [8, 8]); // pendingIndex=2
    const r = applyEvent(pending, ev({ seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 2 } })) as GameView;
    expect(r.pendingIndex).toBeNull();
    expect(r.moves).toHaveLength(3); // не задвоился
  });
  it("несоответствие индекса (рассинхрон) → resync", () => {
    expect(applyEvent(view(), ev({ seq: 6, type: "move", payload: { by: "black", point: [8, 8], move_index: 7 } }))).toBe("resync");
  });
});

describe("status / forbidden / undo / reset / error", () => {
  it("status без winning_line — линия не трогается", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "status", payload: { status: "opponent_thinking" } })) as GameView;
    expect(r.status).toBe("opponent_thinking");
    expect(r.winningLine).toBeNull();
  });
  it("финальный status с winning_line — линия установлена", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "status", payload: { status: "finished_black", winning_line: [[7, 7], [8, 8]] } })) as GameView;
    expect(r.status).toBe("finished_black");
    expect(r.winningLine).toEqual([[7, 7], [8, 8]]);
  });
  it("undo: усечение до move_count, статус awaiting_move, pending/линия/фолы сняты", () => {
    const finished: GameView = { ...view(), status: "finished_black", winningLine: [[7, 7]], pendingIndex: 1 };
    const r = applyEvent(finished, ev({ seq: 6, type: "undo", payload: { move_count: 1 } })) as GameView;
    expect(r.moves).toEqual([[7, 7]]);
    expect(r).toMatchObject({ status: "awaiting_move", pendingIndex: null, winningLine: null, forbidden: [] });
  });
  it("reset → resync", () => {
    expect(applyEvent(view(), ev({ seq: 6, type: "reset", payload: {} }))).toBe("resync");
  });
  it("error — состояние не меняется, кроме курсора (сообщение — забота useGame)", () => {
    const r = applyEvent(view(), ev({ seq: 6, type: "error", payload: { message: "x" } })) as GameView;
    expect(r.cursor).toBe(6);
    expect(r.moves).toEqual(view().moves);
  });
});

describe("placePending", () => {
  it("кладёт камень в конец и помечает pending", () => {
    const r = placePending(view(), [8, 8]);
    expect(r.moves).toEqual([[7, 7], [6, 6], [8, 8]]);
    expect(r.pendingIndex).toBe(2);
  });
});
