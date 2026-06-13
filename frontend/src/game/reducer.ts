// Чистый редьюсер SSE-событий (спека §«Контракт бэка», §«Поток данных»). Без I/O.
import type { GameEventMessage, GameStateDTO, Point } from "./types";
import type { GameView } from "./view";

export function fromState(st: GameStateDTO): GameView {
  const engine = Object.values(st.controllers).find((c) => c.kind === "engine");
  return {
    id: st.id,
    yourColor: st.your_color,
    status: st.status,
    moves: st.moves.map(([x, y]) => [x, y] as Point),
    pendingIndex: null,
    forbidden: st.forbidden.map(([x, y]) => [x, y] as Point),
    winningLine: st.winning_line?.map(([x, y]) => [x, y] as Point) ?? null,
    cursor: st.cursor,
    opponentLevelId: engine?.kind === "engine" ? engine.levelId : null,
  };
}

export function placePending(v: GameView, point: Point): GameView {
  return { ...v, moves: [...v.moves, point], pendingIndex: v.moves.length };
}

const same = (a: Point, b: Point) => a[0] === b[0] && a[1] === b[1];

export function applyEvent(v: GameView, ev: GameEventMessage): GameView | "resync" {
  if (ev.seq <= v.cursor) return v; // дубль реплея — идемпотентный игнор
  if (ev.seq > v.cursor + 1) return "resync"; // пропуск событий
  const base = { ...v, cursor: ev.seq };
  switch (ev.type) {
    case "move": {
      const { point, move_index } = ev.payload;
      const pt: Point = [point[0], point[1]];
      if (base.pendingIndex !== null && move_index === base.pendingIndex && same(base.moves[base.pendingIndex], pt)) {
        return { ...base, pendingIndex: null, forbidden: [] }; // подтверждение оптимистичного
      }
      if (base.pendingIndex === null && move_index === base.moves.length) {
        return { ...base, moves: [...base.moves, pt], forbidden: [] };
      }
      return "resync"; // индекс не сошёлся — состояние устарело
    }
    case "status":
      return {
        ...base,
        status: ev.payload.status,
        winningLine: ev.payload.winning_line?.map(([x, y]) => [x, y] as Point) ?? base.winningLine,
      };
    case "forbidden":
      return { ...base, forbidden: ev.payload.points.map(([x, y]) => [x, y] as Point) };
    case "undo":
      return {
        ...base,
        moves: base.moves.slice(0, ev.payload.move_count),
        status: "awaiting_move",
        pendingIndex: null,
        winningLine: null,
        forbidden: [],
      };
    case "reset":
      return "resync";
    case "error":
      return base; // курсор сдвинут; сообщение пользователю — забота useGame
  }
}
