import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import type { GameSummaryDTO } from "../game/types";
import { favoriteGame, unfavoriteGame, deleteGame } from "../game/api";
import { statusLabel, statusTone, sectionDateLabel } from "../game/format";
import { MiniBoard } from "./MiniBoard";
import styles from "./GameCard.module.css";

// levelName — человекочитаемое имя уровня (резолвит родитель по level_id; сводка несёт только id).
type Props = { game: GameSummaryDTO; levelName?: string; onOpen: (id: string) => void; onChanged: () => void };

const LONG_TAP_MS = 500;
const MENU_W = 184;
const MENU_H = 168; // оценка (min-width 160 + паддинги; ≤3 пункта)

export function GameCard({ game, levelName, onOpen, onChanged }: Props) {
  const [menu, setMenu] = useState(false);
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);
  const downPt = useRef<{ x: number; y: number } | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  function openAt(px: number, py: number) {
    const x = Math.max(8, Math.min(px, window.innerWidth - MENU_W));
    const y = Math.max(8, Math.min(py, window.innerHeight - MENU_H));
    setMenuPos({ x, y });
    setMenu(true);
  }

  function openMenu(e: React.MouseEvent) {
    e.preventDefault();
    openAt(e.clientX, e.clientY);
  }

  function cancelLongTap() {
    if (timer.current !== null) { clearTimeout(timer.current); timer.current = null; }
    downPt.current = null;
  }

  function onPointerDown(e: ReactPointerEvent) {
    if (e.pointerType !== "touch") return; // long-tap — только на тач (спека §6); мышь — правый клик
    downPt.current = { x: e.clientX, y: e.clientY };
    const px = e.clientX, py = e.clientY;
    timer.current = window.setTimeout(() => openAt(px, py), LONG_TAP_MS);
  }

  function onPointerMove(e: ReactPointerEvent) {
    if (downPt.current && Math.hypot(e.clientX - downPt.current.x, e.clientY - downPt.current.y) > 10) {
      cancelLongTap();
    }
  }

  useEffect(() => cancelLongTap, []); // очистка висячего таймера при размонтировании

  // Escape + фокус на первой кнопке при открытии меню
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(false);
    };
    document.addEventListener("keydown", onKey);
    menuRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [menu]);

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    // busy намеренно НЕ сбрасывается на успехе: после onChanged() родитель перезапросит
    // раздел и размонтирует эту карточку — застрявший busy недостижим.
    try { await action(); setMenu(false); onChanged(); }
    catch { setBusy(false); } // меню остаётся — можно повторить
  }

  return (
    <div
      data-testid={`card-${game.id}`}
      className={styles.card}
      role="button"
      tabIndex={0}
      onClick={() => onOpen(game.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(game.id);
        }
      }}
      onContextMenu={openMenu}
      onPointerDown={onPointerDown}
      onPointerUp={cancelLongTap}
      onPointerMove={onPointerMove}
    >
      <div className={styles.thumb}><MiniBoard moves={game.moves} /></div>
      <div className={styles.statusRow}>
        <span className={`${styles.tag} ${styles[statusTone(game.status)]}`}>
          {statusLabel(game.status, game.your_color)}
        </span>
      </div>
      <div className={styles.meta}>
        {game.your_color && (
          <>
            <span className={`${styles.chip} ${game.your_color === "black" ? styles.chipBlack : styles.chipWhite}`} />
            <span>ты — {game.your_color === "black" ? "чёрные" : "белые"}</span>
          </>
        )}
        {game.your_color && levelName && <span className={styles.dot} />}
        {levelName && <span className={styles.levelPill}>{levelName}</span>}
      </div>
      <div className={styles.meta}>
        <span>ход {game.move_count}</span>
        {sectionDateLabel(game.section, game) && (
          <>
            <span className={styles.dot} />
            <span>{sectionDateLabel(game.section, game)}</span>
          </>
        )}
      </div>

      {menu && menuPos && createPortal(
        <>
          {/* backdrop перехватывает клик вне меню → dismiss; stopPropagation, чтобы
              pointerdown/click не всплыли к карточке и не открыли партию */}
          <div
            data-testid="menu-backdrop"
            className={styles.backdrop}
            onPointerDown={(e) => { e.stopPropagation(); setMenu(false); }}
            onClick={(e) => e.stopPropagation()}
          />
          <div
            ref={menuRef}
            className={styles.menu}
            role="menu"
            style={{ left: menuPos.x, top: menuPos.y }}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            {game.section === "finished" && (
              <button role="menuitem" disabled={busy} onClick={() => run(() => favoriteGame(game.id))}>В избранное</button>
            )}
            {game.section === "favorite" && (
              <button role="menuitem" disabled={busy} onClick={() => run(() => unfavoriteGame(game.id))}>Из избранного</button>
            )}
            <button role="menuitem" disabled={busy} onClick={() => run(() => deleteGame(game.id))}>Удалить</button>
          </div>
        </>,
        document.body,
      )}
    </div>
  );
}
