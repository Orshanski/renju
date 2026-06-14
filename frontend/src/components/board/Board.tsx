import { pointLabel } from "../../game/legality";
import { N, PAD, STEP, HOSHI, at } from "../../game/boardGeometry";
import type { Color, Point } from "../../game/types";
import styles from "./Board.module.css";

// Геометрия гобана (N/PAD/STEP/HOSHI/at) — общий boardGeometry, percent-based fluid (спека §«Геометрия»).
const CELLS: Point[] = [];
for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) CELLS.push([x, y]);

type BoardProps = {
  moves: Point[];
  forbidden: Point[];
  zone: Point[] | null; // дебютная зона для рамки (null — рамки нет)
  winningLine: Point[] | null;
  ghostColor: Color; // цвет ходящего — для hover-превью
  canPlayAt: (x: number, y: number) => boolean;
  onPlay: (x: number, y: number) => void;
};

function zoneRect(zone: Point[]) {
  const xs = zone.map((p) => p[0]);
  const ys = zone.map((p) => p[1]);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const w = Math.max(...xs) - minX + 1;
  const h = Math.max(...ys) - minY + 1;
  return {
    left: `${(PAD + (minX - 0.5) * STEP) * 100}%`,
    top: `${(PAD + (minY - 0.5) * STEP) * 100}%`,
    width: `${w * STEP * 100}%`,
    height: `${h * STEP * 100}%`,
  };
}

export function Board({ moves, forbidden, zone, winningLine, ghostColor, canPlayAt, onPlay }: BoardProps) {
  const last = moves.at(-1);
  const lastIdx = moves.length - 1;
  return (
    <div className={styles.goban}>
      <div className={styles.gridLines} />
      {HOSHI.map((p) => (
        <div key={`h${p[0]}-${p[1]}`} className={styles.hoshi} style={at(p)} />
      ))}
      {zone && <div className={styles.zoneFrame} style={zoneRect(zone)} data-testid="zone-frame" />}
      {CELLS.map(([x, y]) => (
        <button
          key={`n${x}-${y}`}
          type="button"
          className={styles.node}
          style={at([x, y])}
          aria-label={pointLabel([x, y])}
          disabled={!canPlayAt(x, y)}
          onClick={() => onPlay(x, y)}
        >
          <span className={`${styles.ghost} ${ghostColor === "black" ? styles.ghostBlack : styles.ghostWhite}`} />
        </button>
      ))}
      {moves.map((m, i) => (
        <div
          key={`s${i}`}
          className={`${styles.stone} ${i % 2 === 0 ? styles.black : styles.white}`}
          style={at(m)}
          data-testid={`stone-${m[0]}-${m[1]}`}
        />
      ))}
      {last && (
        <div
          className={`${styles.last} ${lastIdx % 2 === 0 ? styles.lastOnBlack : styles.lastOnWhite}`}
          style={at(last)}
          data-testid={`last-${last[0]}-${last[1]}`}
        />
      )}
      {forbidden.map((p) => (
        <div key={`f${p[0]}-${p[1]}`} className={styles.forbid} style={at(p)} data-testid={`forbid-${p[0]}-${p[1]}`}>
          ✕
        </div>
      ))}
      {winningLine?.map((p) => (
        <div key={`w${p[0]}-${p[1]}`} className={styles.winMark} style={at(p)} data-testid={`win-${p[0]}-${p[1]}`} />
      ))}
    </div>
  );
}
