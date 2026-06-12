// Зеркало бэк-контракта (спека §«Контракт бэка глазами фронта»). snake_case — как на проводе.
export type Point = [number, number];
export type Color = "black" | "white";
export type GameStatus =
  | "awaiting_move"
  | "opponent_thinking"
  | "finished_black"
  | "finished_white"
  | "finished_draw";

export type ControllerDTO = { kind: "user" } | { kind: "engine"; levelId: string };

export type GameStateDTO = {
  id: string;
  owner_id: number;
  controllers: Partial<Record<Color, ControllerDTO>>;
  your_color: Color | null;
  status: GameStatus;
  moves: Point[];
  undo_count: number;
  cursor: number;
  forbidden: Point[];
  winning_line: Point[] | null;
};

export type LevelDTO = { id: string; name: string };

export type GameEventMessage =
  | { seq: number; type: "move"; payload: { by: Color; point: Point; move_index: number } }
  | { seq: number; type: "status"; payload: { status: GameStatus; winning_line?: Point[] } }
  | { seq: number; type: "forbidden"; payload: { points: Point[] } }
  | { seq: number; type: "undo"; payload: { move_count: number } }
  | { seq: number; type: "error"; payload: { message: string } }
  | { seq: number; type: "reset"; payload: Record<string, never> };
