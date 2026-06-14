import { HOSHI, at } from "../game/boardGeometry";
import type { Point } from "../game/types";
import styles from "./MiniBoard.module.css";

// Статичная миниатюра РЕАЛЬНОЙ позиции для карточки партии — настоящие ходы из
// сводки, без интерактива/ховеров/нодов. Геометрия — общий boardGeometry, поэтому
// камни стоят там же, где на полноразмерной доске. Декоративна для скринридера
// (статус/уровень/счётчик ходов карточка отдаёт текстом) → aria-hidden.
export function MiniBoard({ moves }: { moves: Point[] }) {
  const last = moves.at(-1);
  const lastIdx = moves.length - 1;
  return (
    <div className={styles.mini} aria-hidden="true">
      <div className={styles.grid} />
      {HOSHI.map((p) => (
        <div key={`h${p[0]}-${p[1]}`} className={styles.hoshi} style={at(p)} />
      ))}
      {moves.map((m, i) => (
        <div
          key={`s${i}`}
          data-testid="mini-stone"
          className={`${styles.stone} ${i % 2 === 0 ? styles.black : styles.white}`}
          style={at(m)}
        />
      ))}
      {last && (
        <div
          className={`${styles.last} ${lastIdx % 2 === 0 ? styles.lastOnBlack : styles.lastOnWhite}`}
          style={at(last)}
        />
      )}
    </div>
  );
}
