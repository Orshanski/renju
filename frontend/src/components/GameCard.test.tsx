import { it, expect, vi } from "vitest";
import { render, screen, fireEvent, createEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server, http, HttpResponse } from "../test/msw";
import { GameCard } from "./GameCard";
import type { GameSummaryDTO } from "../game/types";

const finished: GameSummaryDTO = {
  id: "g1", status: "finished_black", section: "finished", level_id: "master",
  your_color: "black", move_count: 3, moves: [[7, 7], [8, 8], [7, 8]],
  favorite: false, updated_at: null, finished_at: "2026-06-12T09:00:00",
};

it("карточка показывает тег статуса, цвет/уровень и мини-доску с камнями", () => {
  render(<GameCard game={finished} levelName="Мастер" onOpen={() => {}} onChanged={() => {}} />);
  expect(screen.getByText("Победа")).toBeInTheDocument();
  expect(screen.getByText(/чёрные/)).toBeInTheDocument();
  expect(screen.getByText("Мастер")).toBeInTheDocument();
  expect(screen.getAllByTestId("mini-stone")).toHaveLength(3);
});

it("карточка без твоего цвета (your_color=null): нет строки «ты — …», статус «Завершено»", () => {
  const noColor: GameSummaryDTO = { ...finished, your_color: null, status: "finished_white" };
  render(<GameCard game={noColor} onOpen={() => {}} onChanged={() => {}} />);
  expect(screen.getByText("Завершено")).toBeInTheDocument();
  expect(screen.queryByText(/ты —/)).toBeNull();
});

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

it("Enter на карточке открывает партию (a11y)", async () => {
  const onOpen = vi.fn();
  render(<GameCard game={finished} onOpen={onOpen} onChanged={() => {}} />);
  fireEvent.keyDown(screen.getByTestId("card-g1"), { key: "Enter" });
  expect(onOpen).toHaveBeenCalledWith("g1");
});

it("клик по фону вне меню закрывает меню", async () => {
  render(<GameCard game={finished} onOpen={() => {}} onChanged={() => {}} />);
  fireEvent.contextMenu(screen.getByTestId("card-g1"));
  expect(await screen.findByRole("menu")).toBeInTheDocument();
  fireEvent.pointerDown(screen.getByTestId("menu-backdrop"));
  expect(screen.queryByRole("menu")).toBeNull();
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

it("slop отменяет long-tap: движение > 10px до таймаута → меню не открылось", () => {
  const makePointerEv = (type: string, pointerType: string, x: number, y: number) => {
    const ev = createEvent[type as "pointerDown"](document.body);
    Object.defineProperty(ev, "pointerType", { value: pointerType });
    Object.defineProperty(ev, "clientX", { value: x });
    Object.defineProperty(ev, "clientY", { value: y });
    return ev;
  };
  vi.useFakeTimers();
  try {
    render(<GameCard game={finished} onOpen={() => {}} onChanged={() => {}} />);
    const card = screen.getByTestId("card-g1");
    // touch down в (0,0)
    const evDown = makePointerEv("pointerDown", "touch", 0, 0);
    fireEvent(card, evDown);
    // move > 10px
    const evMove = makePointerEv("pointerMove", "touch", 15, 0);
    fireEvent(card, evMove);
    // таймаут истёк — но таймер уже отменён
    act(() => { vi.advanceTimersByTime(600); });
    expect(screen.queryByRole("menu")).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

it("Escape закрывает меню", async () => {
  render(<GameCard game={finished} onOpen={() => {}} onChanged={() => {}} />);
  fireEvent.contextMenu(screen.getByTestId("card-g1"));
  expect(await screen.findByRole("menu")).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("menu")).toBeNull();
});
