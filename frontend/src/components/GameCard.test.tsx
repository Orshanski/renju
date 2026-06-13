import { it, expect, vi } from "vitest";
import { render, screen, fireEvent, createEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, http, HttpResponse } from "../test/msw";
import { GameCard } from "./GameCard";
import type { GameSummaryDTO } from "../game/types";

const finished: GameSummaryDTO = {
  id: "g1", status: "finished_black", section: "finished", level_id: "master",
  your_color: "black", move_count: 21, favorite: false, updated_at: null, finished_at: "2026-06-12T09:00:00",
};

it("правый клик по завершённой → «В избранное» → POST favorite, зовёт onChanged", async () => {
  const onChanged = vi.fn();
  server.use(http.post("/api/games/g1/favorite", () => HttpResponse.json(true)));
  render(<GameCard game={finished} onOpen={() => {}} onChanged={onChanged} />);
  fireEvent.contextMenu(screen.getByTestId("card-g1"));
  await userEvent.click(await screen.findByRole("menuitem", { name: "В избранное" }));
  await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
});

it("«Удалить» → DELETE, зовёт onChanged", async () => {
  const onChanged = vi.fn();
  server.use(http.delete("/api/games/g1", () => new HttpResponse(null, { status: 204 })));
  render(<GameCard game={finished} onOpen={() => {}} onChanged={onChanged} />);
  fireEvent.contextMenu(screen.getByTestId("card-g1"));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Удалить" }));
  await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
});

it("у текущей в меню только «Удалить» (нет избранного)", async () => {
  const cur: GameSummaryDTO = { ...finished, id: "g2", status: "awaiting_move", section: "current", finished_at: null, updated_at: "2026-06-13T10:00:00" };
  render(<GameCard game={cur} onOpen={() => {}} onChanged={() => {}} />);
  fireEvent.contextMenu(screen.getByTestId("card-g2"));
  expect(await screen.findByRole("menuitem", { name: "Удалить" })).toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "В избранное" })).toBeNull();
});

it("клик по карточке (не по меню) зовёт onOpen", async () => {
  const onOpen = vi.fn();
  render(<GameCard game={finished} onOpen={onOpen} onChanged={() => {}} />);
  await userEvent.click(screen.getByTestId("card-g1"));
  expect(onOpen).toHaveBeenCalledWith("g1");
});

it("long-tap ТОЛЬКО на тач: touch-pointerdown открывает меню, мышь — нет (спека §6)", () => {
  const pointerDown = (el: Element, pointerType: string) => {
    const ev = createEvent.pointerDown(el);
    Object.defineProperty(ev, "pointerType", { value: pointerType });
    fireEvent(el, ev);
  };
  vi.useFakeTimers();
  try {
    render(<GameCard game={finished} onOpen={() => {}} onChanged={() => {}} />);
    const card = screen.getByTestId("card-g1");
    pointerDown(card, "mouse");
    act(() => { vi.advanceTimersByTime(600); });
    expect(screen.queryByRole("menu")).toBeNull();
    pointerDown(card, "touch");
    act(() => { vi.advanceTimersByTime(600); });
    expect(screen.getByRole("menu")).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
