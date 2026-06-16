import { it, expect } from "vitest";
import { render } from "@testing-library/react";
import { BoardGrid } from "./BoardGrid";
import { N, pos } from "../../game/boardGeometry";

it(`рисует ${N} вертикальных и ${N} горизонтальных линий (всего ${N * 2})`, () => {
  const { container } = render(<BoardGrid />);
  const grid = container.firstChild as HTMLElement;
  // BoardGrid рисует N вертикальных + N горизонтальных div-линий внутри контейнера
  expect(grid.children).toHaveLength(N * 2);
});

it("первая и последняя вертикальные линии совпадают с pos(0) и pos(N-1)", () => {
  const { container } = render(<BoardGrid />);
  const grid = container.firstChild as HTMLElement;
  const vlines = Array.from(grid.children).slice(0, N) as HTMLElement[];
  expect(vlines[0].style.left).toBe(pos(0));
  expect(vlines[N - 1].style.left).toBe(pos(N - 1));
});

it("первая и последняя горизонтальные линии совпадают с pos(0) и pos(N-1)", () => {
  const { container } = render(<BoardGrid />);
  const grid = container.firstChild as HTMLElement;
  const hlines = Array.from(grid.children).slice(N) as HTMLElement[];
  expect(hlines[0].style.top).toBe(pos(0));
  expect(hlines[N - 1].style.top).toBe(pos(N - 1));
});

it("lineWidth передаётся в width вертикальных и height горизонтальных линий", () => {
  const { container } = render(<BoardGrid lineWidth="0.5px" />);
  const grid = container.firstChild as HTMLElement;
  const vline = grid.children[0] as HTMLElement;
  const hline = grid.children[N] as HTMLElement;
  expect(vline.style.width).toBe("0.5px");
  expect(hline.style.height).toBe("0.5px");
});
