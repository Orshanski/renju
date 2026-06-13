import type { Color, GameStatus, Point } from "./types";

// Вью-модель партии (camelCase). pendingIndex — индекс неподтверждённого
// оптимистичного хода в moves (он уже лежит в массиве), null — нет pending.
export type GameView = {
  id: string;
  yourColor: Color | null;
  status: GameStatus;
  moves: Point[];
  pendingIndex: number | null;
  forbidden: Point[];
  winningLine: Point[] | null;
  cursor: number;
  opponentLevelId: string | null;
};
