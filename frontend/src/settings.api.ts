import { apiRequest } from "./api/client";

export interface UserSettings {
  games_limit: number;
  games_limit_enabled: boolean;
  undo_enabled: boolean;
  undo_limit: number | null; // null = ∞
  undo_after_game_end: boolean;
}

export function getSettings(): Promise<UserSettings> {
  return apiRequest<UserSettings>("GET", "/api/settings");
}

export function saveSettings(body: UserSettings): Promise<UserSettings> {
  return apiRequest<UserSettings>("PUT", "/api/settings", body);
}

export function changePassword(current_password: string, new_password: string): Promise<void> {
  return apiRequest<void>("PUT", "/api/settings/password", { current_password, new_password });
}
