import { apiRequest } from "../api/client";

export type LevelConfigDTO = {
  id: string; name: string; strength: number; timeout_ms: number;
  max_depth: number; depth_ceiling: number;
};
export type EngineConfigDTO = { levels: LevelConfigDTO[]; nnue: boolean };
export type EngineConfigUpdate = {
  levels: { id: string; strength: number; timeout_ms: number; max_depth: number }[];
  nnue: boolean;
};

export function getEngineConfig(): Promise<EngineConfigDTO> {
  return apiRequest<EngineConfigDTO>("GET", "/api/admin/engine-config");
}

export function putEngineConfig(body: EngineConfigUpdate): Promise<EngineConfigDTO> {
  return apiRequest<EngineConfigDTO>("PUT", "/api/admin/engine-config", body);
}

export type UserAdminDTO = { id: number; username: string; role: "admin" | "user"; created_at: string };
export type CreateUserBody = { username: string; password: string; role: "admin" | "user" };
export type UpdateUserBody = { role?: "admin" | "user"; password?: string };

export function listUsers(): Promise<UserAdminDTO[]> {
  return apiRequest<UserAdminDTO[]>("GET", "/api/admin/users");
}

export function createUser(body: CreateUserBody): Promise<{ id: number }> {
  return apiRequest<{ id: number }>("POST", "/api/admin/users", body);
}

export function updateUser(id: number, body: UpdateUserBody): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>("PUT", `/api/admin/users/${id}`, body);
}

export function deleteUser(id: number): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>("DELETE", `/api/admin/users/${id}`);
}
