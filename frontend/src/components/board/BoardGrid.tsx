import { N, PAD, STEP, pos } from "../../game/boardGeometry";
import styles from "./BoardGrid.module.css";

// Линии сетки из ТОГО ЖЕ pos(i), что камни/точки (at()) — единый механизм округления,
// сетка не расходится с камнями ни на какой ширине (раньше сетка была CSS-фоном-плиткой
// со своим округлением → расхождение на дробной ширине, rj-2iy).
const ORIGIN = `${PAD * 100}%`;           // = pos(0), начало сетки
const SPAN = `${(N - 1) * STEP * 100}%`; // протяжённость = pos(N-1) - pos(0)

export function BoardGrid({ lineWidth = "1px" }: { lineWidth?: string }) {
  return (
    <div className={styles.grid} aria-hidden="true">
      {Array.from({ length: N }, (_, i) => (
        <div key={`v${i}`} className={styles.v} style={{ left: pos(i), top: ORIGIN, height: SPAN, width: lineWidth }} />
      ))}
      {Array.from({ length: N }, (_, i) => (
        <div key={`h${i}`} className={styles.h} style={{ top: pos(i), left: ORIGIN, width: SPAN, height: lineWidth }} />
      ))}
    </div>
  );
}
