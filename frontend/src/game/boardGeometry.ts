import type { Point } from "./types";

// Геометрия гобана — пропорции прототипа (--step:38px, --pad:30px, сторона 592px).
// Позиции в процентах от квадрата → доска fluid без JS. ЕДИНЫЙ источник для Board
// (интерактивная доска) и MiniBoard (миниатюра карточки) — чтобы камни не разъехались.
export const N = 15;
export const PAD = 30 / 592;
export const STEP = 38 / 592;
export const HOSHI: Point[] = [[3, 3], [11, 3], [3, 11], [11, 11], [7, 7]];

export const pos = (i: number) => `${(PAD + i * STEP) * 100}%`;
export const at = ([x, y]: Point) => ({ left: pos(x), top: pos(y) }); // инлайн — значения из данных (конвенция)
