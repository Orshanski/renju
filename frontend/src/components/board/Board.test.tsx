import { it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Board } from "./Board";
import type { Point } from "../../game/types";

const noop = () => {};
const allow = () => true;
const deny = () => false;

function renderBoard(over: Partial<Parameters<typeof Board>[0]> = {}) {
  const props = {
    moves: [[7, 7], [6, 6]] as Point[],
    forbidden: [] as Point[],
    zone: null as Point[] | null,
    winningLine: null as Point[] | null,
    ghostColor: "black" as const,
    canPlayAt: allow as (x: number, y: number) => boolean,
    onPlay: noop as (x: number, y: number) => void,
    ...over,
  };
  return render(<Board {...props} />);
}

it("рисует 225 узлов и камни позиции (чёрный/белый по чётности)", () => {
  renderBoard();
  expect(screen.getAllByRole("button")).toHaveLength(225);
  expect(screen.getByTestId("stone-7-7").className).toContain("black");
  expect(screen.getByTestId("stone-6-6").className).toContain("white");
});

it("клик по узлу зовёт onPlay с координатами", async () => {
  const onPlay = vi.fn();
  renderBoard({ onPlay });
  await userEvent.click(screen.getByRole("button", { name: "I8" })); // x=8,y=7
  expect(onPlay).toHaveBeenCalledWith(8, 7);
});

it("canPlayAt=false дизейблит узел — клик не проходит", async () => {
  const onPlay = vi.fn();
  renderBoard({ onPlay, canPlayAt: deny });
  expect(screen.getByRole("button", { name: "H8" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "H8" }));
  expect(onPlay).not.toHaveBeenCalled();
});

it("маркер последнего хода стоит на последнем камне", () => {
  renderBoard();
  expect(screen.getByTestId("last-6-6")).toBeInTheDocument();
  expect(screen.queryByTestId("last-7-7")).not.toBeInTheDocument();
});

it("фолы отмечены ✕", () => {
  renderBoard({ forbidden: [[5, 8]] as Point[] });
  expect(screen.getByTestId("forbid-5-8")).toHaveTextContent("✕");
});

it("рамка дебютной зоны видна, когда зона задана, и отсутствует без неё", () => {
  const zone: Point[] = [];
  for (let y = 5; y <= 9; y++) for (let x = 5; x <= 9; x++) zone.push([x, y]);
  const { rerender } = renderBoard({ zone });
  expect(screen.getByTestId("zone-frame")).toBeInTheDocument();
  rerender(
    <Board moves={[[7, 7]] as Point[]} forbidden={[]} zone={null} winningLine={null}
      ghostColor="black" canPlayAt={allow} onPlay={noop} />,
  );
  expect(screen.queryByTestId("zone-frame")).not.toBeInTheDocument();
});

it("выигрышная линия подсвечена меткой на каждом камне", () => {
  renderBoard({ winningLine: [[7, 7], [8, 8]] as Point[] });
  expect(screen.getByTestId("win-7-7")).toBeInTheDocument();
  expect(screen.getByTestId("win-8-8")).toBeInTheDocument();
});
