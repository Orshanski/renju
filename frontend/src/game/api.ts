import { apiRequest } from "../api/client";
import type { GameStateDTO, GameSummaryDTO, LevelDTO, Section } from "./types";

export function createGame(levelId: string): Promise<GameStateDTO> {
  return apiRequest<GameStateDTO>("POST", "/api/games", { opponent: { kind: "engine", levelId } });
}

export function getGame(id: string): Promise<GameStateDTO> {
  return apiRequest<GameStateDTO>("GET", `/api/games/${id}`);
}

export function postMove(id: string, x: number, y: number): Promise<{ accepted: boolean }> {
  return apiRequest<{ accepted: boolean }>("POST", `/api/games/${id}/move`, { x, y });
}

export function postUndo(id: string): Promise<GameStateDTO> {
  return apiRequest<GameStateDTO>("POST", `/api/games/${id}/undo`);
}

// presence: вход на экран партии поднимает/переиспользует процесс движка, выход — гасит,
// если ушло последнее устройство (rj-899). Fire-and-forget: ошибка не валит экран.
export function enterGame(id: string): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>("POST", `/api/games/${id}/enter`);
}

export function leaveGame(id: string): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>("POST", `/api/games/${id}/leave`);
}

export function getLevels(): Promise<LevelDTO[]> {
  return apiRequest<LevelDTO[]>("GET", "/api/levels");
}

export function getGamesSummary(section: Section): Promise<GameSummaryDTO[]> {
  return apiRequest<GameSummaryDTO[]>("GET", `/api/games/summary?section=${section}`);
}

export function favoriteGame(id: string): Promise<true> {
  return apiRequest<true>("POST", `/api/games/${id}/favorite`);
}

export function unfavoriteGame(id: string): Promise<true> {
  return apiRequest<true>("POST", `/api/games/${id}/unfavorite`);
}

export function deleteGame(id: string): Promise<void> {
  return apiRequest<void>("DELETE", `/api/games/${id}`);
}
