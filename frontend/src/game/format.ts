import type { Color, GameStatus, Section } from "./types";

export function statusLabel(status: GameStatus, your: Color | null): string {
  if (status === "awaiting_move") return "Твой ход";
  if (status === "opponent_thinking") return "Ход соперника";
  if (status === "finished_draw") return "Ничья";
  if (your === null) return "Завершено";
  const winner: Color = status === "finished_black" ? "black" : "white";
  return your === winner ? "Победа" : "Поражение";
}

function fmt(iso: string): string {
  // Бэк сериализует datetime как naive UTC (без 'Z'/offset). Строка date-time без
  // обозначения пояса парсится движком JS как ЛОКАЛЬНОЕ время — метка сдвигалась на
  // часовой пояс пользователя. Дописываем 'Z', если пояс не указан → трактуем как UTC.
  const utc = /[zZ]|[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  return new Date(utc).toLocaleString("ru-RU", {
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
