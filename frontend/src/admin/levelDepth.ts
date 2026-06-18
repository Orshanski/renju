// Копия формулы движка Rapfi (skill.h) для ЖИВОГО пересчёта в UI. Сверяется с
// бэк-таблицей unit-тестом — не дрейфует. Источник истины — движок.
const GOD_STRENGTH = 100;
const MAX_SEARCH_DEPTH = 99; // engine/config.toml max_search_depth

export function depthCeiling(strength: number): number {
  return 4 + Math.floor(24 * (1 - Math.pow(0.5, strength / 100)));
}

/**
 * Диапазон [нижняя, верхняя] глубины для уровня index.
 *
 * Нижняя = ВЫСТАВЛЕННАЯ глубина предыдущего уровня (для первого уровня = 1).
 * Верхняя = depthCeiling(strength[index]); Бог (strength=100) → MAX_SEARCH_DEPTH=99.
 */
export function depthRange(index: number, strengths: number[], depths: number[]): [number, number] {
  const strength = strengths[index];
  const hi = strength >= GOD_STRENGTH ? MAX_SEARCH_DEPTH : depthCeiling(strength);
  const lo = index === 0 ? 1 : depths[index - 1];
  return [lo, hi];
}

/** Зажим силы соседями: [сила предыдущего … сила следующего − 1]; первый снизу 1, последний сверху 100. */
export function clampStrength(index: number, value: number, strengths: number[]): number {
  const lo = index === 0 ? 1 : strengths[index - 1];
  const hi = index === strengths.length - 1 ? 100 : strengths[index + 1] - 1;
  return Math.min(Math.max(value, lo), hi);
}
