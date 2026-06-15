import { useEffect, useState } from "react";
import { getLevels } from "./api";
import type { LevelDTO } from "./types";

// Справочник уровней id→имя. Отказ загрузки не критичен (имя — украшение).
export function useLevels() {
  const [levels, setLevels] = useState<LevelDTO[]>([]);
  useEffect(() => {
    let alive = true;
    getLevels()
      .then((ls) => alive && setLevels(ls))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  const byId = new Map(levels.map((l) => [l.id, l.name]));
  return {
    levels,
    nameOf: (id: string | null | undefined): string | undefined =>
      id ? byId.get(id) : undefined,
  };
}
