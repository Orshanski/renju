import { apiRequest } from "../api/client";

export type LevelConfigDTO = { id: string; name: string; strength: number; timeout_ms: number };
export type EngineConfigDTO = { levels: LevelConfigDTO[]; nnue: boolean };
export type EngineConfigUpdate = {
  levels: { id: string; strength: number; timeout_ms: number }[];
  nnue: boolean;
};

export function getEngineConfig(): Promise<EngineConfigDTO> {
  return apiRequest<EngineConfigDTO>("GET", "/api/admin/engine-config");
}

export function putEngineConfig(body: EngineConfigUpdate): Promise<EngineConfigDTO> {
  return apiRequest<EngineConfigDTO>("PUT", "/api/admin/engine-config", body);
}
