import { it, expect, describe } from "vitest";
import { canPlay, canUndo, colorToMove, openingZone, pointLabel } from "./legality";
import type { GameView } from "./view";
import type { Point } from "./types";

const base: GameView = {
  id: "g1", yourColor: "black", status: "awaiting_move",
  moves: [[7, 7], [6, 6]], pendingIndex: null, forbidden: [],
  winningLine: null, cursor: 2, opponentLevelId: "novice",
};
const v = (over: Partial<GameView>): GameView => ({ ...base, ...over });

describe("colorToMove", () => {
  it("чётное число камней → чёрные, нечётное → белые", () => {
    expect(colorToMove(0)).toBe("black");
    expect(colorToMove(1)).toBe("white");
    expect(colorToMove(2)).toBe("black");
  });
});

describe("openingZone", () => {
  it("ход №1 → 3×3 вокруг центра", () => {
    const z = openingZone(1)!;
    expect(z).toHaveLength(9);
    expect(z).toContainEqual([6, 6]);
    expect(z).not.toContainEqual([5, 5]);
  });
  it("ход №2 → 5×5", () => {
    const z = openingZone(2)!;
    expect(z).toHaveLength(25);
    expect(z).toContainEqual([5, 5]);
    expect(z).not.toContainEqual([4, 7]);
  });
  it("ход №3+ → null (без ограничений)", () => {
    expect(openingZone(3)).toBeNull();
    expect(openingZone(0)).not.toBeNull(); // в партии не встречается (центр предзаполнен), но геометрия честная
  });
});

describe("canPlay", () => {
  it("свободная точка в свой ход (зона 5×5, ход №2) — можно", () => {
    expect(canPlay(v({}), [8, 7])).toBe(true);
  });
  it("занято — нельзя", () => expect(canPlay(v({}), [7, 7])).toBe(false));
  it("вне дебютной зоны (ход №2, 5×5) — нельзя", () => expect(canPlay(v({}), [1, 1])).toBe(false));
  it("после дебюта зона снята", () => {
    const view = v({ moves: [[7, 7], [6, 6], [8, 8], [9, 9]] }); // 4 камня → ход №4, зоны нет
    expect(canPlay(view, [1, 1])).toBe(true);
  });
  it("фол-точка — нельзя", () => {
    const view = v({ moves: [[7, 7], [6, 6], [8, 8], [9, 9]], forbidden: [[1, 1]] });
    expect(canPlay(view, [1, 1])).toBe(false);
  });
  it("не твоя очередь — нельзя", () => {
    expect(canPlay(v({ moves: [[7, 7]] }), [6, 6])).toBe(false); // 1 камень → ход белых, мы чёрные
  });
  it("соперник думает / партия кончена / pending — нельзя", () => {
    expect(canPlay(v({ status: "opponent_thinking" }), [8, 7])).toBe(false);
    expect(canPlay(v({ status: "finished_black" }), [8, 7])).toBe(false);
    expect(canPlay(v({ pendingIndex: 1 }), [8, 7])).toBe(false);
  });
  it("за доской — нельзя", () => expect(canPlay(v({}), [15, 0] as Point)).toBe(false));
});

describe("canUndo (зеркало undo_truncate: чёрным нужно ≥3 камней, белым ≥2)", () => {
  it("чёрные: 2 камня — нечего, 3 — можно", () => {
    expect(canUndo(v({ moves: [[7, 7], [6, 6]] }))).toBe(false);
    expect(canUndo(v({ moves: [[7, 7], [6, 6], [8, 8]], status: "opponent_thinking" }))).toBe(false); // думает — нельзя
    expect(canUndo(v({ moves: [[7, 7], [6, 6], [8, 8]] }))).toBe(true);
  });
  it("белые: 1 камень — нечего, 2 — можно", () => {
    expect(canUndo(v({ yourColor: "white", moves: [[7, 7]] }))).toBe(false);
    expect(canUndo(v({ yourColor: "white", moves: [[7, 7], [6, 6]] }))).toBe(true);
  });
  it("после конца партии — можно (дефолтная политика), при pending — нельзя", () => {
    expect(canUndo(v({ status: "finished_black", moves: [[7, 7], [6, 6], [8, 8]] }))).toBe(true);
    expect(canUndo(v({ pendingIndex: 2, moves: [[7, 7], [6, 6], [8, 8]] }))).toBe(false);
  });
});

describe("pointLabel", () => {
  it("колонка A–O по x, строка y+1", () => {
    expect(pointLabel([0, 0])).toBe("A1");
    expect(pointLabel([7, 7])).toBe("H8");
    expect(pointLabel([14, 14])).toBe("O15");
  });
});
