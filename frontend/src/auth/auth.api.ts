import { apiRequest } from "../api/client";
import type { User } from "../types";

// POST /login → { ok, user: User } — user ВЛОЖЕН; логин исключён из глобального 401 (skipAuthRedirect)
export async function apiLogin(username: string, password: string): Promise<User> {
  const resp = await apiRequest<{ ok: boolean; user: User }>(
    "POST", "/api/auth/login", { username, password }, { skipAuthRedirect: true },
  );
  return resp.user;
}

// GET /me → User плоско
export function apiMe(): Promise<User> {
  return apiRequest<User>("GET", "/api/auth/me");
}

export async function apiLogout(): Promise<void> {
  await apiRequest("POST", "/api/auth/logout"); // тело ответа не используется
}
