import type { Color, GameStatus, Section } from "./types";

export function statusLabel(status: GameStatus, your: Color | null): string {
  if (status === "awaiting_move") return "Твой ход";
  if (status === "opponent_thinking") return "Ход соперника";
  if (status === "finished_draw") return "Ничья";
  const winner: Color = status === "finished_black" ? "black" : "white";
  return your === winner ? "Победа" : "Поражение";
}

function fmt(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function sectionDateLabel(
  section: Section,
  g: { updated_at: string | null; finished_at: string | null },
): string {
  if (section === "current") return g.updated_at ? `Обновлено ${fmt(g.updated_at)}` : "";
  return g.finished_at ? `Завершено ${fmt(g.finished_at)}` : "";
}
