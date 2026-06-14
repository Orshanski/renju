import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MiniBoard } from "./MiniBoard";
import type { Point } from "../game/types";

it("рисует по камню на каждый ход позиции", () => {
  const moves: Point[] = [[7, 7], [8, 8], [7, 8]];
  render(<MiniBoard moves={moves} />);
  expect(screen.getAllByTestId("mini-stone")).toHaveLength(3);
});

it("пустая позиция — без камней (доска просто пустая)", () => {
  render(<MiniBoard moves={[]} />);
  expect(screen.queryAllByTestId("mini-stone")).toHaveLength(0);
});
