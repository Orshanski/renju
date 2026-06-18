import { describe, it, expect } from "vitest";
import { depthCeiling, depthRange, clampStrength } from "./levelDepth";

describe("depthCeiling — копия формулы движка, сверка с бэк-таблицей", () => {
  const table: [number, number][] = [
    [0, 4], [5, 4], [6, 4], [7, 5], [12, 5], [13, 6], [15, 6], [19, 6],
    [20, 7], [26, 7], [27, 8], [33, 8], [34, 9], [41, 9], [42, 10], [49, 10],
    [50, 11], [58, 11], [59, 12], [67, 12], [68, 13], [77, 13], [78, 14],
    [88, 14], [89, 15], [99, 15], [100, 16],
  ];
  it.each(table)("s=%i → %i", (s, d) => expect(depthCeiling(s)).toBe(d));
});

describe("depthRange — [нижняя…верхняя], нижняя=верх предыдущего, Бог особый", () => {
  it("Новичок: [1 … 4]", () => expect(depthRange(0, [5, 15])).toEqual([1, 4]));
  it("средний уровень: [верх пред … потолок]", () =>
    expect(depthRange(1, [5, 15, 35])).toEqual([4, 6]));
  it("Бог (последний, сила 100): [16 … 99]", () =>
    expect(depthRange(6, [5, 15, 35, 55, 75, 90, 100])).toEqual([16, 99]));
});

describe("clampStrength — зажим силы соседями", () => {
  it("Новичок снизу 1", () => expect(clampStrength(0, 0, [5, 15])).toBe(1));
  it("средний: [сила пред … сила след − 1]", () =>
    expect(clampStrength(1, 2, [5, 15, 35])).toBe(5));
  it("Бог сверху 100", () => expect(clampStrength(6, 150, [5, 15, 35, 55, 75, 90, 100])).toBe(100));
});
