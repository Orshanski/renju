// Чистое зеркало серверных правил ввода (app/domain/{opening,game}.py) — для UX.
// Сервер остаётся последней инстанцией; рассинхрон лечится ресинхроном (спека).
import type { Color, Point } from "./types";
import type { GameView } from "./view";

export const BOARD_SIZE = 15;
const CX = 7; // центр (7,7) предзаполнен при создании партии

export function colorToMove(moveCount: number): Color {
  return moveCount % 2 === 0 ? "black" : "white";
}

export function openingZone(moveCount: number): Point[] | null {
  // зеркало opening_zone: 1 → 3×3, 2 → 5×5, дальше без ограничений
  const radius = moveCount === 0 ? 0 : moveCount === 1 ? 1 : moveCount === 2 ? 2 : null;
  if (radius === null) return null;
  const pts: Point[] = [];
  for (let y = CX - radius; y <= CX + radius; y++)
    for (let x = CX - radius; x <= CX + radius; x++) pts.push([x, y]);
  return pts;
}

const has = (pts: Point[], [x, y]: Point) => pts.some(([px, py]) => px === x && py === y);

export function canPlay(view: GameView, point: Point): boolean {
  const [x, y] = point;
  if (view.status !== "awaiting_move" || view.pendingIndex !== null) return false;
  if (view.yourColor === null || colorToMove(view.moves.length) !== view.yourColor) return false;
  if (x < 0 || x >= BOARD_SIZE || y < 0 || y >= BOARD_SIZE) return false;
  // forbidden непуст ТОЛЬКО на ходу чёрных (сервер шлёт фолы лишь для чёрной позиции) — безусловная проверка эквивалентна серверному гейту «фол только чёрным»
  if (has(view.moves, point) || has(view.forbidden, point)) return false;
  const zone = openingZone(view.moves.length);
  return zone === null || has(zone, point);
}

export function canUndo(view: GameView): boolean {
  // зеркало undo_truncate (preset=1): нужен индекс k ≥ 1 чётности своего цвета
  if (view.pendingIndex !== null || view.status === "opponent_thinking") return false;
  if (view.yourColor === null) return false;
  return view.moves.length >= (view.yourColor === "black" ? 3 : 2);
}

export function pointLabel([x, y]: Point): string {
  return String.fromCharCode(65 + x) + String(y + 1); // A–O + 1–15 (как в прототипе)
}
